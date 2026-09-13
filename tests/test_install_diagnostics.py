from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_oss_installer import checks_by_name, installer, preflight_args, ready_host


@pytest.mark.parametrize("error,category", [
    ("permission denied while connecting to synthetic-private-endpoint", "permission-denied"),
    ("Access is denied: synthetic-private-endpoint", "permission-denied"),
    ("Cannot connect to the Docker daemon at synthetic-private-endpoint", "engine-unreachable"),
    ("dial synthetic-private-endpoint: connection refused", "engine-unreachable"),
    ("synthetic-private-output", "unavailable"),
])
def test_runtime_failure_categories_never_return_diagnostic_content(monkeypatch, error, category):
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 1, "synthetic-private-output", error))
    assert installer._runtime_probe_status(["docker", "info"]) == category


@pytest.mark.parametrize("exception,category", [
    (subprocess.TimeoutExpired("synthetic-private-command", 20), "timed-out"),
    (PermissionError("synthetic-private-path"), "client-permission"),
    (OSError("synthetic-private-error"), "unavailable"),
])
def test_runtime_probe_exceptions_are_fixed_categories(monkeypatch, exception, category):
    def fail(command):
        raise exception
    monkeypatch.setattr(installer, "_probe", fail)
    assert installer._runtime_probe_status(["docker", "info"]) == category


def test_socket_permission_remedy_preserves_endpoint_and_account_privacy(tmp_path, ready_host, monkeypatch):
    original = installer._probe
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 1, "", "permission denied at synthetic-private-endpoint")
                        if "{{.ServerVersion}}" in command else original(command))
    result = installer._collect_preflight("none", preflight_args(tmp_path))
    check = checks_by_name(result)["docker-access"]
    assert check.state == "fail" and check.blocking
    assert "fresh login session" in check.remedy
    assert "group or ACL" in check.remedy and "Do not assume" in check.remedy
    assert "synthetic-private" not in json.dumps(result.payload())


@pytest.mark.parametrize("endpoint,scope", [
    ("unix:///synthetic-private/socket", "unix-socket"),
    ("ssh://synthetic-private", "remote-or-tcp"),
    ("tcp://synthetic-private", "remote-or-tcp"),
    ("synthetic-private-output", "unknown"),
])
def test_engine_scope_uses_selected_context_without_returning_endpoint(monkeypatch, endpoint, scope):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 0, endpoint, ""))
    assert installer._docker_engine_scope() == scope


def test_explicit_context_takes_precedence_over_docker_host(monkeypatch):
    monkeypatch.setenv("DOCKER_CONTEXT", "synthetic-private-context")
    monkeypatch.setenv("DOCKER_HOST", "unix:///synthetic-private/socket")
    monkeypatch.setattr(installer, "_probe", lambda command: subprocess.CompletedProcess(command, 0, "ssh://synthetic-private-engine", ""))
    assert installer._docker_engine_scope() == "remote-or-tcp"
    monkeypatch.delenv("DOCKER_CONTEXT")
    monkeypatch.setattr(installer, "_probe", lambda command: pytest.fail("DOCKER_HOST override must not inspect the default context"))
    assert installer._docker_engine_scope() == "unix-socket"


def memory_tree(tmp_path, version="v2", *, namespace_root=False):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    proc.joinpath("meminfo").write_text("MemTotal: 67108864 kB\nMemAvailable: 50331648 kB\n")
    mount = tmp_path / "synthetic cgroup"
    child = mount if namespace_root else mount / "workload" / "nested"
    child.mkdir(parents=True)
    location = "/" if namespace_root else "/workload/nested"
    proc.joinpath("self/cgroup").write_text(f"0::{location}\n" if version == "v2" else f"5:memory:{location}\n")
    mount_text = str(mount).replace(" ", "\\040")
    mounted_root = "/outer/namespace" if namespace_root else "/"
    suffix = "cgroup2 cgroup rw" if version == "v2" else "cgroup cgroup rw,memory"
    proc.joinpath("self/mountinfo").write_text(f"10 9 0:1 {mounted_root} {mount_text} rw - {suffix}\n")
    limit_name, usage_name = (("memory.max", "memory.current") if version == "v2" else
                              ("memory.limit_in_bytes", "memory.usage_in_bytes"))
    directory = child
    while True:
        directory.joinpath(limit_name).write_text("max" if version == "v2" else str(2 ** 63 - 4096))
        directory.joinpath(usage_name).write_text("0")
        if directory == mount:
            break
        directory = directory.parent
    return proc, child, mount, limit_name, usage_name


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_memory_applies_visible_parent_capacity_and_remaining_budget(tmp_path, version):
    proc, child, mount, limit_name, usage_name = memory_tree(tmp_path, version)
    child.joinpath(limit_name).write_text(str(32 * 1024 ** 3))
    child.joinpath(usage_name).write_text(str(4 * 1024 ** 3))
    child.parent.joinpath(limit_name).write_text(str(16 * 1024 ** 3))
    child.parent.joinpath(usage_name).write_text(str(14 * 1024 ** 3))
    assert installer._memory_snapshot(proc) == (16 * 1024 ** 3, 2 * 1024 ** 3, "limited")


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_unlimited_memory_preserves_memavailable_instead_of_free_memory(tmp_path, version):
    proc, *_ = memory_tree(tmp_path, version)
    assert installer._memory_snapshot(proc) == (64 * 1024 ** 3, 48 * 1024 ** 3, "unlimited")


def test_memory_namespace_root_and_usage_above_limit_are_bounded(tmp_path):
    proc, child, mount, limit_name, usage_name = memory_tree(tmp_path, namespace_root=True)
    child.joinpath(limit_name).write_text(str(4 * 1024 ** 3))
    child.joinpath(usage_name).write_text(str(5 * 1024 ** 3))
    assert installer._memory_snapshot(proc) == (4 * 1024 ** 3, 0, "limited")


@pytest.mark.parametrize("fault", ["missing", "malformed", "traversal"])
def test_unverified_memory_hierarchy_is_reported_unknown(tmp_path, fault):
    proc, child, mount, limit_name, _ = memory_tree(tmp_path)
    if fault == "missing":
        child.joinpath(limit_name).unlink()
    elif fault == "malformed":
        child.joinpath(limit_name).write_text("synthetic-private-content")
    else:
        proc.joinpath("self/cgroup").write_text("0::/../../synthetic-private-path\n")
    assert installer._memory_snapshot(proc) == (64 * 1024 ** 3, 48 * 1024 ** 3, "unknown")


def test_missing_memavailable_is_unknown_instead_of_total_as_free(tmp_path):
    proc, *_ = memory_tree(tmp_path)
    proc.joinpath("meminfo").write_text("MemTotal: 67108864 kB\nMemFree: 1024 kB\n")
    assert installer._memory_snapshot(proc) is None


@pytest.mark.parametrize("total,available,state", [(16, 3, "fail"), (8, 8, "fail"), (32, 24, "pass")])
def test_memory_planning_is_advisory_and_never_blocks(tmp_path, ready_host, monkeypatch, total, available, state):
    monkeypatch.setattr(installer, "_docker_engine_scope", lambda: "unix-socket")
    monkeypatch.setattr(installer, "_memory_snapshot", lambda: (total * 1024 ** 3, available * 1024 ** 3, "limited"))
    result = installer._collect_preflight("none", preflight_args(tmp_path))
    check = checks_by_name(result)["memory"]
    assert check.state == state and not check.blocking and result.ready
    assert "installer process" in check.remedy


@pytest.mark.parametrize("scope", ["remote-or-tcp", "unknown"])
def test_memory_never_claims_remote_engine_ready_from_client_ram(monkeypatch, scope):
    monkeypatch.setattr(installer, "_memory_snapshot", lambda: (64 * 1024 ** 3, 48 * 1024 ** 3, "unlimited"))
    check = installer._memory_advisory("none", scope)
    assert check.state == "unknown" and not check.blocking
    assert "Installer process view" in check.observed
    assert "not measured" in check.observed or "unverified" in check.observed


@pytest.mark.parametrize("boundary,fault,observation", [
    ("leaf", "owner", "Existing creation directory is not owned"),
    ("leaf", "permissions", "Existing creation directory permits group"),
    ("parent", "owner", "A protected ancestor is owned by neither"),
    ("parent", "permissions", "A protected ancestor permits replacement"),
    ("parent", "access", "A protected ancestor lacks read or search"),
])
def test_storage_diagnoses_boundary_without_disclosing_paths_or_owners(tmp_path, ready_host, monkeypatch, boundary, fault, observation):
    parent = tmp_path / "synthetic-private-parent"
    node = parent / "synthetic-private-node"
    node.mkdir(parents=True, mode=0o700)
    parent.chmod(0o700)
    selected = node if boundary == "leaf" else parent
    if fault == "permissions":
        selected.chmod(0o777)
    elif fault == "owner":
        original = Path.stat
        def metadata(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == selected:
                fields = list(result)
                fields[4] = 23456
                return os.stat_result(fields)
            return result
        monkeypatch.setattr(Path, "stat", metadata)
    else:
        original = os.access
        monkeypatch.setattr(os, "access", lambda path, mode: False if path == selected else original(path, mode))
    args = preflight_args(tmp_path)
    args.root = node
    result = installer._collect_preflight("none", args)
    check = checks_by_name(result)["node-storage"]
    assert check.state == "fail" and check.blocking
    assert observation in check.observed
    encoded = json.dumps(result.payload())
    assert "synthetic-private" not in encoded and "23456" not in encoded


def test_cpu_health_handoff_is_neutral_when_selected_capabilities_pass(tmp_path, monkeypatch, capsys):
    from tests.test_first_run_handoff import configured_node
    root, _, _ = configured_node(tmp_path.resolve())
    capsys.readouterr()
    payload = {"product": "RecordBench", "status": "degraded", "storage": {"status": "ready"},
               "capabilities": {"source_review": "ready", "malware_scan": "ready",
                                "answering": "temporarily unavailable", "search": "word search only"}}
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(installer, "_login_reachable", lambda root: True)
    installer._wait_health(installer.Console(color=False), root)
    output = capsys.readouterr().out
    assert "[!!]" not in output
    assert "CPU evaluation is ready" in output and "were not selected" in output
    assert installer._install_progress(root)["phases"]["selected_capabilities"] == "complete"


def test_diagnostics_emit_only_whitelisted_metadata_and_historical_phases(tmp_path, request, monkeypatch, capsys):
    from tests.test_first_run_handoff import configured_node
    root, _, _ = configured_node(tmp_path.resolve())
    record = json.loads(root.joinpath("installation.json").read_text())
    record.update(release_id=installer.VERSION + "-" + "a" * 12, private_extra="synthetic-private-value")
    root.joinpath("installation.json").write_text(json.dumps(record))
    installer._install_phase(root, "prepared", "complete")
    request.getfixturevalue("ready_host")
    capsys.readouterr()
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(installer, "_saved_models_verified", lambda *a: pytest.fail("receipt hashed model bytes"))
    monkeypatch.setattr(installer, "_password", lambda *a: pytest.fail("receipt requested a password"))
    monkeypatch.setattr(installer, "_run", lambda *a, **kw: pytest.fail("receipt ran a service command"))
    monkeypatch.setattr(installer, "_login_reachable", lambda *a: pytest.fail("receipt probed login"))
    monkeypatch.setattr(installer, "_atomic_private_write", lambda *a: pytest.fail("receipt changed node state"))
    monkeypatch.setattr(sys, "argv", ["install", "diagnostics", "--root", str(root)])
    assert installer.main() == 0
    output = capsys.readouterr().out
    receipt = json.loads(output)
    assert receipt["schema_version"] == 1 and receipt["kind"] == "installation-diagnostics"
    assert receipt["installation"] == {"state": "validated", "release_id": record["release_id"], "auth": "local", "models": "none"}
    assert receipt["saved_phases_state"] == "historical-not-refreshed"
    assert receipt["saved_phases"]["prepared"] == "complete"
    assert receipt["live_health"] == "not-probed" and receipt["browser_sign_in"] == "not-verified"
    assert receipt["model_bytes"] == "not-verified"
    for private in ("synthetic-private", str(root), "alice.admin", "Alice Administrator", "recordbench.example.test"):
        assert private not in output
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_diagnostics_unsafe_saved_node_is_one_fixed_failure(tmp_path, ready_host, monkeypatch, capsys):
    node = tmp_path / "synthetic-private-node"
    node.mkdir(mode=0o700)
    node.joinpath("installation.json").write_text('{"private": "synthetic-private-value"}')
    monkeypatch.setattr(sys, "argv", ["install", "diagnostics", "--root", str(node)])
    assert installer.main() == 1
    output = capsys.readouterr().out
    receipt = json.loads(output)
    assert receipt["installation"] == {"state": "unavailable-or-unsafe"}
    assert receipt["preflight"]["checks"][0]["name"] == "saved-node"
    assert "synthetic-private" not in output
    assert all(state == "not-verified" for state in receipt["saved_phases"].values())


def test_receipt_rejects_extra_phase_keys_and_arbitrary_release_metadata(tmp_path):
    from tests.test_first_run_handoff import configured_node
    root, _, _ = configured_node(tmp_path.resolve())
    record, _ = installer._installed_release(root)
    installer._install_phase(root, "prepared", "complete")
    path = root / "state/install-progress.json"
    progress = json.loads(path.read_text())
    progress["phases"]["synthetic-private-key"] = "synthetic-private-value"
    path.write_text(json.dumps(progress))
    receipt = installer._diagnostic_receipt(installer.PreflightResult(()), record, root, saved_state="validated")
    assert receipt["installation"]["release_id"] == "unavailable"
    assert receipt["saved_phases_state"] == "unavailable"
    assert "synthetic-private" not in json.dumps(receipt)
