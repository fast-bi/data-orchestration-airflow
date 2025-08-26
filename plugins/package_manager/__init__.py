from __future__ import annotations

import os
import logging
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Tuple, List,  Dict, Optional
from flask import g, current_app
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from airflow.plugins_manager import AirflowPlugin
from airflow.security import permissions
from airflow.www.auth import has_access
from flask import Blueprint, request, jsonify, session
from flask_appbuilder import BaseView, expose
from airflow.utils.session import provide_session
from airflow.configuration import conf
from airflow.www.app import csrf
import pickle
import base64

logger = logging.getLogger(__name__)

# Global token storage that persists across all requests and view instances
_global_token_storage: Dict[str, Dict] = {}

class PackageManagerView(BaseView):
    route_base = "/package-manager"
    default_view = "list_packages"
    
    def __init__(self):
        super().__init__()
        self.namespace = os.getenv('AIRFLOW__KUBERNETES_ENVIRONMENT_VARIABLES__AIRFLOW_NAMESPACE', 'data-orchestration')
        self.configmap_name = 'airflow-config-pypi'
        self.component_labels = ['worker', 'triggerer', 'scheduler']
        self._operation_tokens: Dict[str, Dict] = {}
        # Initialize class-level storage if it doesn't exist
        if not hasattr(PackageManagerView, '_class_tokens'):
            PackageManagerView._class_tokens: Dict[str, Dict] = {}
        # Also initialize a module-level storage for even more persistence
        if not hasattr(self.__class__, '_module_tokens'):
            self.__class__._module_tokens: Dict[str, Dict] = {}

    def _get_current_user_identifier(self) -> str:
            """Get current user identifier safely"""
            try:
                # Try different user attributes that might be available
                if hasattr(g, 'user'):
                    if hasattr(g.user, 'email'):
                        return g.user.email
                    elif hasattr(g.user, 'username'):
                        return g.user.username
                    elif hasattr(g.user, 'user'):
                        return str(g.user.user)
                
                # Fallback to session user if available
                from flask_login import current_user
                if hasattr(current_user, 'email'):
                    return current_user.email
                elif hasattr(current_user, 'username'):
                    return current_user.username
                
                # Last resort: return user ID
                return str(current_user.get_id())
                
            except Exception as e:
                logger.warning(f"Could not get user identifier: {e}")
                return "unknown_user"

    def _clean_expired_tokens(self):
        """Clean up expired tokens"""
        global _global_token_storage
        now = datetime.now()
        
        # Clean instance tokens
        self._operation_tokens = {
            token: data for token, data in self._operation_tokens.items()
            if data['expires_at'] > now
        }
        
        # Clean class-level tokens
        PackageManagerView._class_tokens = {
            token: data for token, data in PackageManagerView._class_tokens.items()
            if data['expires_at'] > now
        }
        
        # Clean module-level tokens
        self.__class__._module_tokens = {
            token: data for token, data in self.__class__._module_tokens.items()
            if data['expires_at'] > now
        }
        
        # Clean session tokens
        try:
            if 'package_manager_tokens' in session:
                session['package_manager_tokens'] = {
                    token: data for token, data in session['package_manager_tokens'].items()
                    if data['expires_at'] > now
                }
                session.modified = True
        except Exception as e:
            logger.warning(f"Could not clean session tokens: {e}")
        
        # Clean global tokens
        _global_token_storage = {
            token: data for token, data in _global_token_storage.items()
            if data['expires_at'] > now
        }

    def _generate_operation_token(self, operation: str, package: str) -> str:
        """Generate a secure token for package operations"""
        global _global_token_storage
        self._clean_expired_tokens()
        
        # Get user identifier
        user = self._get_current_user_identifier()
        
        # Generate a secure random token
        token = secrets.token_urlsafe(32)
        
        # Store token with metadata in multiple storage locations for persistence
        token_data = {
            'operation': operation,
            'package': package,
            'user': user,
            'expires_at': datetime.now() + timedelta(hours=1)
        }
        
        # Store in all storage locations for maximum persistence
        self._operation_tokens[token] = token_data
        PackageManagerView._class_tokens[token] = token_data
        self.__class__._module_tokens[token] = token_data
        _global_token_storage[token] = token_data  # Global storage
        
        # Also store in Flask session as a fallback
        try:
            if 'package_manager_tokens' not in session:
                session['package_manager_tokens'] = {}
            session['package_manager_tokens'][token] = token_data
            session.modified = True
        except Exception as e:
            logger.warning(f"Could not store token in session: {e}")
        
        logger.info(f"Generated token for operation '{operation}' on package '{package}' for user '{user}'")
        
        return token

    def _verify_operation_token(self, token: str, operation: str, package: str) -> bool:
        """Verify the operation token"""
        global _global_token_storage
        self._clean_expired_tokens()
        
        # Try all storage locations in order of persistence
        token_data = self._operation_tokens.get(token)
        if not token_data:
            token_data = PackageManagerView._class_tokens.get(token)
        if not token_data:
            token_data = self.__class__._module_tokens.get(token)
        if not token_data:
            token_data = _global_token_storage.get(token)  # Global storage
        if not token_data:
            # Try Flask session as final fallback
            try:
                if 'package_manager_tokens' in session:
                    token_data = session['package_manager_tokens'].get(token)
            except Exception as e:
                logger.warning(f"Could not access session tokens: {e}")
            
        if not token_data:
            logger.warning(f"Token not found: {token[:10]}...")
            return False

        user = self._get_current_user_identifier()
        
        # Log token verification details
        logger.info(f"Token verification - Operation: {operation}, Package: {package}, User: {user}")
        
        is_valid = (
            token_data['operation'] == operation and
            token_data['package'] == package and
            token_data['user'] == user and
            token_data['expires_at'] > datetime.now()
        )

        # Remove token after verification (one-time use)
        if is_valid:
            self._operation_tokens.pop(token, None)
            PackageManagerView._class_tokens.pop(token, None)
            self.__class__._module_tokens.pop(token, None)
            _global_token_storage.pop(token, None)  # Global storage
            # Also remove from session
            try:
                if 'package_manager_tokens' in session:
                    session['package_manager_tokens'].pop(token, None)
                    session.modified = True
            except Exception as e:
                logger.warning(f"Could not remove token from session: {e}")
            logger.info("Token verified successfully")

        return is_valid

    def _init_kubernetes(self) -> Tuple[client.CoreV1Api, client.AppsV1Api]:
        """Initialize Kubernetes clients with error handling"""
        try:
            config.load_incluster_config()
            core_v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()
            return core_v1, apps_v1
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise RuntimeError("Failed to connect to Kubernetes cluster")

    def _validate_package_name(self, package: str) -> bool:
        """Validate package name format"""
        if not package or not isinstance(package, str):
            return False
        # Basic validation for package name format (you can enhance this)
        return len(package.strip()) > 0 and ' ' not in package

    def _extract_package_name(self, package: str) -> str:
        """Extract package name without version"""
        try:
            return package.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0].split('~=')[0].split('!=')[0].strip()
        except Exception:
            # Fallback: return the original package if parsing fails
            return package.strip()

    def _extract_package_version(self, package: str) -> str:
        """Extract package version if present"""
        if '==' in package:
            return package.split('==')[1]
        elif '>=' in package:
            return package.split('>=')[1]
        elif '<=' in package:
            return package.split('<=')[1]
        elif '>' in package:
            return package.split('>')[1]
        elif '<' in package:
            return package.split('<')[1]
        elif '~=' in package:
            return package.split('~=')[1]
        elif '!=' in package:
            return package.split('!=')[1]
        return None

    def _get_configmap(self, v1: client.CoreV1Api) -> Tuple[client.V1ConfigMap, List[str]]:
        """Get ConfigMap and parse packages"""
        try:
            configmap = v1.read_namespaced_config_map(self.configmap_name, self.namespace)
            requirements = configmap.data.get('requirements.txt', '')
            packages = [line.strip() for line in requirements.split('\n') if line.strip()]
            return configmap, packages
        except ApiException as e:
            logger.error(f"Failed to read ConfigMap: {e}")
            raise RuntimeError(f"ConfigMap {self.configmap_name} not found")

    def _restart_airflow_pods(self, core_v1: client.CoreV1Api, apps_v1: client.AppsV1Api):
        """Restart Airflow components by scaling down/up StatefulSets and Deployments"""
        try:
            # Get all pods with component labels
            for component in self.component_labels:
                label_selector = f"component={component}"
                
                try:
                    # Handle StatefulSets
                    statefulsets = apps_v1.list_namespaced_stateful_set(
                        namespace=self.namespace,
                        label_selector=label_selector
                    )
                    
                    for sts in statefulsets.items:
                        logger.info(f"Scaling down StatefulSet {sts.metadata.name}")
                        # Scale down
                        sts.spec.replicas = 0
                        apps_v1.patch_namespaced_stateful_set_scale(
                            name=sts.metadata.name,
                            namespace=self.namespace,
                            body={'spec': {'replicas': 0}}
                        )
                        
                        # Wait briefly
                        time.sleep(5)
                        
                        # Scale back up
                        original_replicas = sts.spec.replicas or 1
                        apps_v1.patch_namespaced_stateful_set_scale(
                            name=sts.metadata.name,
                            namespace=self.namespace,
                            body={'spec': {'replicas': original_replicas}}
                        )
                    
                    # Handle Deployments
                    deployments = apps_v1.list_namespaced_deployment(
                        namespace=self.namespace,
                        label_selector=label_selector
                    )
                    
                    for deploy in deployments.items:
                        logger.info(f"Scaling down Deployment {deploy.metadata.name}")
                        # Scale down
                        deploy.spec.replicas = 0
                        apps_v1.patch_namespaced_deployment_scale(
                            name=deploy.metadata.name,
                            namespace=self.namespace,
                            body={'spec': {'replicas': 0}}
                        )
                        
                        # Wait briefly
                        time.sleep(5)
                        
                        # Scale back up
                        original_replicas = deploy.spec.replicas or 1
                        apps_v1.patch_namespaced_deployment_scale(
                            name=deploy.metadata.name,
                            namespace=self.namespace,
                            body={'spec': {'replicas': original_replicas}}
                        )
                
                except ApiException as e:
                    logger.error(f"Error handling component {component}: {e}")
                    continue

            logger.info("Successfully restarted Airflow components")
            
        except Exception as e:
            logger.error(f"Failed to restart Airflow components: {e}")
            raise RuntimeError("Failed to restart Airflow components")

    @csrf.exempt
    @expose("/generate_token", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def generate_token(self):
        """Generate operation token"""
        try:
            operation = request.json.get('operation')
            package = request.json.get('package')
            
            if not operation or not package:
                return jsonify({'error': 'Operation and package are required'}), 400

            if operation not in ['add', 'remove', 'update']:
                return jsonify({'error': 'Invalid operation'}), 400

            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            token = self._generate_operation_token(operation, package)
            
            return jsonify({
                'token': token,
                'expires_in': 3600  # 1 hour in seconds
            })

        except Exception as e:
            logger.error(f"Error generating token: {e}")
            return jsonify({'error': 'Failed to generate token'}), 500

    @csrf.exempt
    @expose("/", methods=['GET'])
    @expose("/list_packages", methods=['GET'])
    @has_access([(permissions.ACTION_CAN_READ, permissions.RESOURCE_ADMIN_MENU)])
    def list_packages(self):
        try:
            core_v1, _ = self._init_kubernetes()
            _, packages = self._get_configmap(core_v1)
            return self.render_template(
                "package_manager/list_packages.html",
                packages=packages
            )
        except Exception as e:
            logger.error(f"Error in list_packages: {e}")
            return jsonify({'error': str(e)}), 500

    @csrf.exempt
    @expose("/add", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def add_package(self):
        """Add a new package to requirements"""
        try:
            package = request.json.get('package')
            token = request.json.get('token')
            
            if not package or not token:
                return jsonify({'error': 'Package and token are required'}), 400

            if not self._verify_operation_token(token, 'add', package):
                return jsonify({'error': 'Invalid or expired token'}), 403

            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            core_v1, apps_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)

            if package in packages:
                return jsonify({'error': 'Package already installed'}), 400

            packages.append(package)
            configmap.data['requirements.txt'] = '\n'.join(packages)

            try:
                core_v1.patch_namespaced_config_map(self.configmap_name, self.namespace, configmap)
                self._restart_airflow_pods(core_v1, apps_v1)
                logger.info(f"Package {package} added successfully")
                logger.warning(f"Package {package} added by user {g.user.email} from IP {request.remote_addr}")
                return jsonify({'success': True, 'message': f'Package {package} added successfully'})
            except ApiException as e:
                logger.error(f"Failed to update ConfigMap: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

        except Exception as e:
            logger.error(f"Error in add_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @csrf.exempt
    @expose("/remove", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def remove_package(self):
        """Remove a package from requirements"""
        try:
            package = request.json.get('package')
            token = request.json.get('token')
            
            if not package or not token:
                return jsonify({'error': 'Package and token are required'}), 400

            if not self._verify_operation_token(token, 'remove', package):
                return jsonify({'error': 'Invalid or expired token'}), 403

            if not self._validate_package_name(package):
                return jsonify({'error': 'Invalid package name'}), 400

            core_v1, apps_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)

            if package not in packages:
                return jsonify({'error': 'Package not found'}), 404

            packages.remove(package)
            configmap.data['requirements.txt'] = '\n'.join(packages)

            try:
                core_v1.patch_namespaced_config_map(self.configmap_name, self.namespace, configmap)
                self._restart_airflow_pods(core_v1, apps_v1)
                logger.info(f"Package {package} removed successfully")
                return jsonify({'success': True, 'message': f'Package {package} removed successfully'})
            except ApiException as e:
                logger.error(f"Failed to update ConfigMap: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

        except Exception as e:
            logger.error(f"Error in remove_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @csrf.exempt
    @expose("/update", methods=['POST'])
    @has_access([(permissions.ACTION_CAN_EDIT, permissions.RESOURCE_ADMIN_MENU)])
    def update_package(self):
        """Update a package version in requirements"""
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

            # Extract package names to ensure we're updating the same package
            old_package_name = self._extract_package_name(old_package)
            new_package_name = self._extract_package_name(new_package)
            
            if old_package_name != new_package_name:
                return jsonify({'error': 'Cannot change package name during update'}), 400

            core_v1, apps_v1 = self._init_kubernetes()
            configmap, packages = self._get_configmap(core_v1)

            if old_package not in packages:
                return jsonify({'error': 'Package not found'}), 404

            # Replace the old package with the new one
            package_index = packages.index(old_package)
            packages[package_index] = new_package
            configmap.data['requirements.txt'] = '\n'.join(packages)

            try:
                core_v1.patch_namespaced_config_map(self.configmap_name, self.namespace, configmap)
                self._restart_airflow_pods(core_v1, apps_v1)
                logger.info(f"Package {old_package} updated to {new_package} successfully")
                logger.warning(f"Package {old_package} updated to {new_package} by user {g.user.email} from IP {request.remote_addr}")
                return jsonify({'success': True, 'message': f'Package {old_package} updated to {new_package} successfully'})
            except ApiException as e:
                logger.error(f"Failed to update ConfigMap: {e}")
                return jsonify({'error': 'Failed to update package list'}), 500

        except Exception as e:
            logger.error(f"Error in update_package: {e}")
            return jsonify({'error': 'Internal server error'}), 500

# Create Flask Blueprint
package_manager_bp = Blueprint(
    "package_manager",
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/package_manager'
)

# Plugin Class
class PackageManagerPlugin(AirflowPlugin):
    name = "package_manager"
    flask_blueprints = [package_manager_bp]
    appbuilder_views = [{
        "name": "Package Manager",
        "category": "Admin",
        "view": PackageManagerView()
    }]