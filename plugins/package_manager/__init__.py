from __future__ import annotations

import os
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Tuple, List, Dict

from flask import g, request, jsonify, session, Blueprint
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from airflow.plugins_manager import AirflowPlugin
from airflow.security import permissions
from airflow.www.auth import has_access
from flask_appbuilder import BaseView, expose
from airflow.www.app import csrf

from . import k8s_rollout

logger = logging.getLogger(__name__)

# ConfigMap annotations recording the previous state for inspection / rollback.
ANNOTATION_PREV_REQS = "fast.bi/previous-requirements"
ANNOTATION_MODIFIED_BY = "fast.bi/last-modified-by"
ANNOTATION_MODIFIED_AT = "fast.bi/last-modified-at"

# Operation token lifetime.
TOKEN_TTL = timedelta(hours=1)
ALLOWED_OPERATIONS = ("add", "remove", "update", "rollback")

# Single module-level token store. Flask session is used as a fallback so tokens
# survive when the request is served by a different gunicorn worker process.
_operation_tokens: Dict[str, Dict[str, Any]] = {}


class PackageManagerView(BaseView):
    route_base = "/package-manager"
    default_view = "list_packages"

    def __init__(self):
        super().__init__()
        self.namespace = os.getenv(
            'AIRFLOW__KUBERNETES_ENVIRONMENT_VARIABLES__AIRFLOW_NAMESPACE',
            'data-orchestration',
        )
        self.configmap_name = 'airflow-config-pypi'

    # ------------------------------------------------------------------ #
    # User identity
    # ------------------------------------------------------------------ #
    def _get_current_user_identifier(self) -> str:
        """Get current user identifier safely."""
        try:
            if hasattr(g, 'user'):
                if hasattr(g.user, 'email'):
                    return g.user.email
                elif hasattr(g.user, 'username'):
                    return g.user.username
                elif hasattr(g.user, 'user'):
                    return str(g.user.user)

            from flask_login import current_user
            if hasattr(current_user, 'email'):
                return current_user.email
            elif hasattr(current_user, 'username'):
                return current_user.username
            return str(current_user.get_id())
        except Exception as e:
            logger.warning(f"Could not get user identifier: {e}")
            return "unknown_user"

    # ------------------------------------------------------------------ #
    # Operation tokens (single store + session fallback)
    # ------------------------------------------------------------------ #
    def _clean_expired_tokens(self) -> None:
        """Remove expired tokens from the module store and the session."""
        now = datetime.now()
        for token in [t for t, d in _operation_tokens.items() if d['expires_at'] <= now]:
            _operation_tokens.pop(token, None)
        try:
            sess_tokens = session.get('package_manager_tokens')
            if sess_tokens:
                session['package_manager_tokens'] = {
                    t: d for t, d in sess_tokens.items() if d['expires_at'] > now
                }
                session.modified = True
        except Exception as e:
            logger.warning(f"Could not clean session tokens: {e}")

    def _generate_operation_token(self, operation: str, package: str) -> str:
        """Generate a secure, single-use token for a package operation."""
        self._clean_expired_tokens()
        user = self._get_current_user_identifier()
        token = secrets.token_urlsafe(32)
        token_data = {
            'operation': operation,
            'package': package,
            'user': user,
            'expires_at': datetime.now() + TOKEN_TTL,
        }
        _operation_tokens[token] = token_data
        try:
            sess_tokens = session.get('package_manager_tokens', {})
            sess_tokens[token] = token_data
            session['package_manager_tokens'] = sess_tokens
            session.modified = True
        except Exception as e:
            logger.warning(f"Could not store token in session: {e}")
        logger.info(f"Generated token for '{operation}' on '{package}' for user '{user}'")
        return token

    def _verify_operation_token(self, token: str, operation: str, package: str) -> bool:
        """Verify and consume a one-time operation token."""
        self._clean_expired_tokens()
        token_data = _operation_tokens.get(token)
        if not token_data:
            try:
                token_data = session.get('package_manager_tokens', {}).get(token)
            except Exception as e:
                logger.warning(f"Could not access session tokens: {e}")
        if not token_data:
            logger.warning(f"Token not found: {token[:10]}...")
            return False

        user = self._get_current_user_identifier()
        is_valid = (
            token_data['operation'] == operation
            and token_data['package'] == package
            and token_data['user'] == user
            and token_data['expires_at'] > datetime.now()
        )
        if is_valid:
            _operation_tokens.pop(token, None)
            try:
                sess_tokens = session.get('package_manager_tokens')
                if sess_tokens:
                    sess_tokens.pop(token, None)
                    session.modified = True
            except Exception as e:
                logger.warning(f"Could not remove token from session: {e}")
            logger.info("Token verified successfully")
        return is_valid

    # ------------------------------------------------------------------ #
    # Kubernetes / kubectl helpers
    # ------------------------------------------------------------------ #
    def _init_kubernetes(self) -> client.CoreV1Api:
        """Initialize the in-cluster Kubernetes client for ConfigMap access."""
        try:
            config.load_incluster_config()
            return client.CoreV1Api()
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise RuntimeError("Failed to connect to Kubernetes cluster")

    def _snapshot_components(self) -> List[Dict[str, Any]]:
        """Capture current replica/rollout state of managed components."""
        return k8s_rollout.snapshot_components(self.namespace)

    def _rollout_restart(self) -> List[str]:
        """Trigger a rolling restart of all managed components (no downscale)."""
        return k8s_rollout.rollout_restart(self.namespace)

    def _rollout_state(self) -> Dict[str, Any]:
        """Return per-component rollout progress derived from a fresh snapshot."""
        return k8s_rollout.rollout_state(self.namespace)

    # ------------------------------------------------------------------ #
    # Package / ConfigMap helpers
    # ------------------------------------------------------------------ #
    def _validate_package_name(self, package: str) -> bool:
        """Validate package name format."""
        if not package or not isinstance(package, str):
            return False
        return len(package.strip()) > 0 and ' ' not in package

    def _extract_package_name(self, package: str) -> str:
        """Extract package name without version specifier."""
        try:
            return package.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0] \
                .split('<')[0].split('~=')[0].split('!=')[0].strip()
        except Exception:
            return package.strip()

    def _get_configmap(self, v1: client.CoreV1Api) -> Tuple[client.V1ConfigMap, List[str]]:
        """Get the requirements ConfigMap and parse the package list."""
        try:
            configmap = v1.read_namespaced_config_map(self.configmap_name, self.namespace)
            requirements = (configmap.data or {}).get('requirements.txt', '')
            packages = [line.strip() for line in requirements.split('\n') if line.strip()]
            return configmap, packages
        except ApiException as e:
            logger.error(f"Failed to read ConfigMap: {e}")
            raise RuntimeError(f"ConfigMap {self.configmap_name} not found")

    def _commit_change(
        self,
        core_v1: client.CoreV1Api,
        configmap: client.V1ConfigMap,
        packages: List[str],
        previous_requirements: str,
    ) -> Dict[str, Any]:
        """Snapshot state, persist new requirements + previous-state annotations, restart.

        Returns the captured previous state so the caller can surface a before/after view.
        """
        previous_state = self._snapshot_components()

        annotations = configmap.metadata.annotations or {}
        annotations[ANNOTATION_PREV_REQS] = previous_requirements
        annotations[ANNOTATION_MODIFIED_BY] = self._get_current_user_identifier()
        annotations[ANNOTATION_MODIFIED_AT] = datetime.now().isoformat()
        configmap.metadata.annotations = annotations

        if configmap.data is None:
            configmap.data = {}
        configmap.data['requirements.txt'] = '\n'.join(packages)

        core_v1.patch_namespaced_config_map(self.configmap_name, self.namespace, configmap)
        restarted = self._rollout_restart()

        return {
            "previous_requirements": [
                p.strip() for p in previous_requirements.split('\n') if p.strip()
            ],
            "previous_state": previous_state,
            "restarted": restarted,
        }

    # ------------------------------------------------------------------ #
    # HTTP endpoints
    # ------------------------------------------------------------------ #
    @csrf.exempt
    @expose("/generate_token", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def generate_token(self):
        """Generate a single-use operation token."""
        try:
            operation = request.json.get('operation')
            package = request.json.get('package')

            if not operation or not package:
                return jsonify({'error': 'Operation and package are required'}), 400
            if operation not in ALLOWED_OPERATIONS:
                return jsonify({'error': 'Invalid operation'}), 400
            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            token = self._generate_operation_token(operation, package)
            return jsonify({'token': token, 'expires_in': int(TOKEN_TTL.total_seconds())})
        except Exception as e:
            logger.error(f"Error generating token: {e}")
            return jsonify({'error': 'Failed to generate token'}), 500

    @csrf.exempt
    @expose("/", methods=['GET'])
    @expose("/list_packages", methods=['GET'])
    @has_access([(permissions.ACTION_CAN_READ, permissions.RESOURCE_ADMIN_MENU)])
    def list_packages(self):
        try:
            core_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)
            annotations = configmap.metadata.annotations or {}
            previous = annotations.get(ANNOTATION_PREV_REQS, '')
            return self.render_template(
                "package_manager/list_packages.html",
                packages=packages,
                previous_requirements=[p.strip() for p in previous.split('\n') if p.strip()],
                last_modified_by=annotations.get(ANNOTATION_MODIFIED_BY, ''),
                last_modified_at=annotations.get(ANNOTATION_MODIFIED_AT, ''),
            )
        except Exception as e:
            logger.error(f"Error in list_packages: {e}")
            return jsonify({'error': str(e)}), 500

    @expose("/status", methods=['GET'])
    @has_access([(permissions.ACTION_CAN_READ, permissions.RESOURCE_ADMIN_MENU)])
    def status(self):
        """Report rollout progress per managed component."""
        try:
            return jsonify(self._rollout_state())
        except Exception as e:
            logger.error(f"Error in status: {e}")
            return jsonify({'error': str(e)}), 500

    @csrf.exempt
    @expose("/add", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def add_package(self):
        """Add a new package to requirements and roll out a restart."""
        try:
            package = request.json.get('package')
            token = request.json.get('token')

            if not package or not token:
                return jsonify({'error': 'Package and token are required'}), 400
            if not self._verify_operation_token(token, 'add', package):
                return jsonify({'error': 'Invalid or expired token'}), 403
            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            core_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)
            if package in packages:
                return jsonify({'error': 'Package already installed'}), 400

            previous_requirements = (configmap.data or {}).get('requirements.txt', '')
            packages.append(package)

            try:
                result = self._commit_change(core_v1, configmap, packages, previous_requirements)
            except (ApiException, RuntimeError) as e:
                logger.error(f"Failed to apply package change: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

            logger.warning(
                f"Package {package} added by user "
                f"{self._get_current_user_identifier()} from IP {request.remote_addr}"
            )
            return jsonify({
                'success': True,
                'message': f'Package {package} added; components restarting (rolling)',
                'previous_requirements': result['previous_requirements'],
                'previous_state': result['previous_state'],
            })
        except Exception as e:
            logger.error(f"Error in add_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @csrf.exempt
    @expose("/remove", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def remove_package(self):
        """Remove a package from requirements and roll out a restart."""
        try:
            package = request.json.get('package')
            token = request.json.get('token')

            if not package or not token:
                return jsonify({'error': 'Package and token are required'}), 400
            if not self._verify_operation_token(token, 'remove', package):
                return jsonify({'error': 'Invalid or expired token'}), 403
            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            core_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)
            if package not in packages:
                return jsonify({'error': 'Package not found'}), 404

            previous_requirements = (configmap.data or {}).get('requirements.txt', '')
            packages.remove(package)

            try:
                result = self._commit_change(core_v1, configmap, packages, previous_requirements)
            except (ApiException, RuntimeError) as e:
                logger.error(f"Failed to apply package change: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

            logger.warning(
                f"Package {package} removed by user "
                f"{self._get_current_user_identifier()} from IP {request.remote_addr}"
            )
            return jsonify({
                'success': True,
                'message': f'Package {package} removed; components restarting (rolling)',
                'previous_requirements': result['previous_requirements'],
                'previous_state': result['previous_state'],
            })
        except Exception as e:
            logger.error(f"Error in remove_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @csrf.exempt
    @expose("/update", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def update_package(self):
        """Update a package version in requirements and roll out a restart."""
        try:
            old_package = request.json.get('old_package')
            new_package = request.json.get('new_package')
            token = request.json.get('token')

            if not old_package or not new_package or not token:
                return jsonify({'error': 'Old package, new package, and token are required'}), 400
            if not self._verify_operation_token(token, 'update', old_package):
                return jsonify({'error': 'Invalid or expired token'}), 403
            if not self._validate_package_name(old_package) or not self._validate_package_name(new_package):
                return jsonify({'error': 'Invalid package name'}), 400
            if self._extract_package_name(old_package) != self._extract_package_name(new_package):
                return jsonify({'error': 'Cannot change package name during update'}), 400

            core_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)
            if old_package not in packages:
                return jsonify({'error': 'Package not found'}), 404

            previous_requirements = (configmap.data or {}).get('requirements.txt', '')
            packages[packages.index(old_package)] = new_package

            try:
                result = self._commit_change(core_v1, configmap, packages, previous_requirements)
            except (ApiException, RuntimeError) as e:
                logger.error(f"Failed to apply package change: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

            logger.warning(
                f"Package {old_package} updated to {new_package} by user "
                f"{self._get_current_user_identifier()} from IP {request.remote_addr}"
            )
            return jsonify({
                'success': True,
                'message': f'Package {old_package} updated to {new_package}; components restarting (rolling)',
                'previous_requirements': result['previous_requirements'],
                'previous_state': result['previous_state'],
            })
        except Exception as e:
            logger.error(f"Error in update_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @csrf.exempt
    @expose("/rollback", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def rollback(self):
        """Restore the previous requirements snapshot and roll out a restart."""
        try:
            token = request.json.get('token')
            if not token:
                return jsonify({'error': 'Token is required'}), 400
            if not self._verify_operation_token(token, 'rollback', 'requirements'):
                return jsonify({'error': 'Invalid or expired token'}), 403

            core_v1 = self._init_kubernetes()
            configmap, _ = self._get_configmap(core_v1)
            annotations = configmap.metadata.annotations or {}
            previous = annotations.get(ANNOTATION_PREV_REQS)
            if previous is None:
                return jsonify({'error': 'No previous state to roll back to'}), 404

            current_requirements = (configmap.data or {}).get('requirements.txt', '')
            packages = [line.strip() for line in previous.split('\n') if line.strip()]

            try:
                result = self._commit_change(core_v1, configmap, packages, current_requirements)
            except (ApiException, RuntimeError) as e:
                logger.error(f"Failed to roll back: {e}")
                return jsonify({'error': 'Failed to roll back requirements'}), 500

            logger.warning(
                f"Requirements rolled back by user "
                f"{self._get_current_user_identifier()} from IP {request.remote_addr}"
            )
            return jsonify({
                'success': True,
                'message': 'Rolled back to previous requirements; components restarting (rolling)',
                'previous_state': result['previous_state'],
            })
        except Exception as e:
            logger.error(f"Error in rollback: {e}")
            return jsonify({'error': 'Internal server error'}), 500


# Flask Blueprint
package_manager_bp = Blueprint(
    "package_manager",
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/package_manager',
)


# Plugin Class
class PackageManagerPlugin(AirflowPlugin):
    name = "package_manager"
    flask_blueprints = [package_manager_bp]
    appbuilder_views = [{
        "name": "Package Manager",
        "category": "Admin",
        "view": PackageManagerView(),
    }]
