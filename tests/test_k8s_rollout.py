"""Unit tests for the dependency-free rollout helpers.

These tests import only ``k8s_rollout`` (stdlib-only), so they run without
Airflow / Flask / the kubernetes client installed.

    pytest tests/test_k8s_rollout.py
"""
import json
import subprocess
from pathlib import Path

import pytest

# Load the helper directly from the plugin directory without importing the
# Airflow-dependent package __init__.
import importlib.util

_HELPER = Path(__file__).resolve().parents[1] / "plugins" / "package_manager" / "k8s_rollout.py"
_spec = importlib.util.spec_from_file_location("k8s_rollout", _HELPER)
k8s_rollout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k8s_rollout)


# --------------------------------------------------------------------------- #
# run_kubectl: validation + arg construction (no shell)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_ns", ["", "Bad_NS", "ns!", "-leading", "x" * 64])
def test_run_kubectl_rejects_invalid_namespace(bad_ns):
    with pytest.raises(k8s_rollout.KubectlError):
        k8s_rollout.run_kubectl(bad_ns, ["get", "pods"])


def test_run_kubectl_requires_binary(monkeypatch):
    monkeypatch.setattr(k8s_rollout.shutil, "which", lambda _: None)
    with pytest.raises(k8s_rollout.KubectlError, match="kubectl binary not found"):
        k8s_rollout.run_kubectl("data-orchestration", ["get", "pods"])


def test_run_kubectl_builds_list_form_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(k8s_rollout.shutil, "which", lambda _: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s_rollout.subprocess, "run", fake_run)

    out = k8s_rollout.run_kubectl("data-orchestration", ["get", "deploy"])

    assert out == "ok"
    # namespace is a discrete list element, never interpolated into a shell string
    assert captured["cmd"] == ["kubectl", "-n", "data-orchestration", "get", "deploy"]
    assert captured["kwargs"]["check"] is True
    assert "shell" not in captured["kwargs"]


def test_run_kubectl_wraps_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="forbidden")

    monkeypatch.setattr(k8s_rollout.shutil, "which", lambda _: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s_rollout.subprocess, "run", fake_run)

    with pytest.raises(k8s_rollout.KubectlError, match="forbidden"):
        k8s_rollout.run_kubectl("data-orchestration", ["rollout", "restart", "deploy"])


def test_run_kubectl_wraps_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 30))

    monkeypatch.setattr(k8s_rollout.shutil, "which", lambda _: "/usr/bin/kubectl")
    monkeypatch.setattr(k8s_rollout.subprocess, "run", fake_run)

    with pytest.raises(k8s_rollout.KubectlError, match="timed out"):
        k8s_rollout.run_kubectl("data-orchestration", ["get", "pods"])


# --------------------------------------------------------------------------- #
# parse_components
# --------------------------------------------------------------------------- #
def _component_payload():
    return json.dumps({
        "items": [
            {
                "kind": "StatefulSet",
                "metadata": {"name": "airflow-worker", "labels": {"component": "worker"}},
                "spec": {"replicas": 4},
                "status": {"readyReplicas": 4, "updatedReplicas": 4, "availableReplicas": 4},
            },
            {
                "kind": "Deployment",
                "metadata": {"name": "airflow-scheduler", "labels": {"component": "scheduler"}},
                "spec": {"replicas": 2},
                "status": {"readyReplicas": 1, "updatedReplicas": 1},
            },
        ]
    })


def test_parse_components_extracts_fields():
    components = k8s_rollout.parse_components(_component_payload())
    assert len(components) == 2
    worker = components[0]
    assert worker["kind"] == "StatefulSet"
    assert worker["component"] == "worker"
    assert worker["desired"] == 4
    assert worker["ready"] == 4
    # missing availableReplicas defaults to 0
    assert components[1]["available"] == 0


def test_parse_components_handles_bad_input():
    assert k8s_rollout.parse_components("not json") == []
    assert k8s_rollout.parse_components(None) == []
    assert k8s_rollout.parse_components('{"items": []}') == []


# --------------------------------------------------------------------------- #
# derive_rollout_state
# --------------------------------------------------------------------------- #
def test_derive_rollout_state_in_progress():
    components = k8s_rollout.parse_components(_component_payload())
    state = k8s_rollout.derive_rollout_state(components)
    by_name = {c["name"]: c for c in state["components"]}
    assert by_name["airflow-worker"]["complete"] is True
    assert by_name["airflow-scheduler"]["complete"] is False
    assert state["in_progress"] is True


def test_derive_rollout_state_all_complete():
    components = [
        {"name": "w", "desired": 4, "ready": 4, "updated": 4},
        {"name": "s", "desired": 2, "ready": 2, "updated": 2},
    ]
    state = k8s_rollout.derive_rollout_state(components)
    assert state["in_progress"] is False
    assert all(c["complete"] for c in state["components"])


def test_derive_rollout_state_zero_desired_is_not_complete():
    state = k8s_rollout.derive_rollout_state([{"name": "x", "desired": 0, "ready": 0, "updated": 0}])
    assert state["components"][0]["complete"] is False
    assert state["in_progress"] is True


def test_derive_rollout_state_empty():
    state = k8s_rollout.derive_rollout_state([])
    assert state == {"components": [], "in_progress": False}


def test_derive_rollout_state_does_not_mutate_input():
    original = [{"name": "w", "desired": 4, "ready": 4, "updated": 4}]
    k8s_rollout.derive_rollout_state(original)
    assert "complete" not in original[0]  # immutable: input untouched


# --------------------------------------------------------------------------- #
# rollout_restart / snapshot_components integration with run_kubectl
# --------------------------------------------------------------------------- #
def test_rollout_restart_uses_selector_and_kinds(monkeypatch):
    captured = {}

    def fake_run_kubectl(namespace, args, timeout=30):
        captured["namespace"] = namespace
        captured["args"] = args
        return "deployment.apps/airflow-scheduler restarted\nstatefulset.apps/airflow-worker restarted\n"

    monkeypatch.setattr(k8s_rollout, "run_kubectl", fake_run_kubectl)
    restarted = k8s_rollout.rollout_restart("data-orchestration")

    assert captured["args"][:3] == ["rollout", "restart", k8s_rollout.MANAGED_KINDS]
    assert k8s_rollout.COMPONENT_SELECTOR in captured["args"]
    assert restarted == [
        "deployment.apps/airflow-scheduler restarted",
        "statefulset.apps/airflow-worker restarted",
    ]


def test_snapshot_components_returns_empty_on_failure(monkeypatch):
    def boom(namespace, args, timeout=30):
        raise k8s_rollout.KubectlError("403")

    monkeypatch.setattr(k8s_rollout, "run_kubectl", boom)
    assert k8s_rollout.snapshot_components("data-orchestration") == []


def test_component_selector_covers_all_managed_components():
    for component in ("worker", "triggerer", "scheduler"):
        assert component in k8s_rollout.COMPONENT_SELECTOR
