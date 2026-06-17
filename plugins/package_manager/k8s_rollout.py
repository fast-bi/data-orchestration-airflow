"""Dependency-free helpers for rolling-restarting Airflow components via kubectl.

This module deliberately imports only the standard library so it can be unit
tested without Airflow / Flask / the kubernetes client installed. The Airflow
plugin view (``__init__.py``) delegates all rollout logic here.
"""
from __future__ import annotations

import re
import json
import shutil
import logging
import subprocess
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Airflow components managed by the package manager, matched via the `component` label.
MANAGED_COMPONENTS: Tuple[str, ...] = ("worker", "triggerer", "scheduler")
# Set-based label selector understood by kubectl: component in (worker,triggerer,scheduler)
COMPONENT_SELECTOR = f"component in ({','.join(MANAGED_COMPONENTS)})"
# Both workload kinds are restarted in a single kubectl call.
MANAGED_KINDS = "deployment,statefulset"

# RFC 1123 namespace validation (defence-in-depth before the value reaches kubectl).
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


class KubectlError(RuntimeError):
    """Raised when a kubectl invocation fails or the environment is invalid."""


def run_kubectl(namespace: str, args: List[str], timeout: int = 30) -> str:
    """Run a kubectl command using list-form args (never a shell) and return stdout.

    Raises ``KubectlError`` on invalid namespace, missing binary, timeout, or
    non-zero exit. Using list-form args means values like the namespace can never
    be interpreted as shell syntax.
    """
    if not NAMESPACE_PATTERN.match(namespace or ""):
        raise KubectlError(f"Invalid namespace: {namespace!r}")
    if not shutil.which("kubectl"):
        raise KubectlError("kubectl binary not found in image")

    cmd = ["kubectl", "-n", namespace, *args]
    logger.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
    except subprocess.TimeoutExpired as exc:
        raise KubectlError(f"kubectl timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        logger.error("kubectl failed (rc=%s): %s", exc.returncode, detail)
        raise KubectlError(f"kubectl error: {detail}") from exc
    return result.stdout


def parse_components(raw_json: str) -> List[Dict[str, Any]]:
    """Parse `kubectl get deploy,sts -o json` output into a flat component list."""
    try:
        payload = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return []

    components: List[Dict[str, Any]] = []
    for item in payload.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        components.append({
            "kind": item.get("kind", ""),
            "name": meta.get("name", ""),
            "component": meta.get("labels", {}).get("component", ""),
            "desired": spec.get("replicas"),
            "ready": status.get("readyReplicas", 0),
            "updated": status.get("updatedReplicas", 0),
            "available": status.get("availableReplicas", 0),
        })
    return components


def derive_rollout_state(components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Annotate each component with `complete` and return aggregate rollout state."""
    annotated: List[Dict[str, Any]] = []
    for component in components:
        desired = component.get("desired") or 0
        component = dict(component)
        component["complete"] = (
            desired > 0
            and component.get("updated", 0) == desired
            and component.get("ready", 0) == desired
        )
        annotated.append(component)
    in_progress = (
        (not all(c.get("complete") for c in annotated)) if annotated else False
    )
    return {"components": annotated, "in_progress": in_progress}


def snapshot_components(namespace: str) -> List[Dict[str, Any]]:
    """Capture the current replica/rollout state of managed components.

    Returns an empty list (rather than raising) so a snapshot failure never blocks
    the package operation it precedes.
    """
    try:
        raw = run_kubectl(
            namespace, ["get", MANAGED_KINDS, "-l", COMPONENT_SELECTOR, "-o", "json"]
        )
    except KubectlError as exc:
        logger.warning("Could not snapshot component state: %s", exc)
        return []
    return parse_components(raw)


def rollout_restart(namespace: str) -> List[str]:
    """Trigger a rolling restart of all managed components without changing replicas.

    Equivalent to `kubectl rollout restart`: patches each workload's pod template
    with a restart annotation so Kubernetes recreates pods gradually (rolling),
    preserving the configured replica count. No scale-to-zero, no outage.
    """
    output = run_kubectl(
        namespace,
        ["rollout", "restart", MANAGED_KINDS, "-l", COMPONENT_SELECTOR],
        timeout=60,
    )
    restarted = [line.strip() for line in output.splitlines() if line.strip()]
    logger.info("Rollout restart triggered: %s", restarted)
    return restarted


def rollout_state(namespace: str) -> Dict[str, Any]:
    """Return per-component rollout progress derived from a fresh snapshot."""
    return derive_rollout_state(snapshot_components(namespace))
