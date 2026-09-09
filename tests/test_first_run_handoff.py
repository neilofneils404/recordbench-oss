from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from case_intelligence.local_accounts import LocalAccountRepository
from tests.test_oss_installer import installer

ROOT = Path(__file__).parents[1]
PASSWORD = "synthetic-handoff-password"


def configured_node(tmp_path):
    root = tmp_path / "Synthetic Node"
    console = installer.Console(color=False)
    args = installer._parser().parse_args(["install", "--auth", "local", "--enable-account-management",
        "--models", "none", "--non-interactive", "--prepare-only", "--admin-username", "alice.admin", "--admin-display-name", "Alice Administrator"])
    paths = installer._prepare_directories(console, root, storage_root=None, resume=False, dry_run=False)
    cert, key = paths["tls"] / "synthetic.crt", paths["tls"] / "synthetic.key"
    cert.write_text("synthetic certificate")
    key.write_text("synthetic key")
    args.tls_cert, args.tls_key = cert, key
    installer._configure(console, args, root, paths, "synthetic-release", ROOT, ())
    return root, args, paths


def test_prepared_handoff_does_not_claim_browser_login_or_running(tmp_path, capsys):
    root, args, paths = configured_node(tmp_path)
    installer._install_phase(root, "prepared", "complete")
    installer._handoff(installer.Console(color=False), root)
    output = capsys.readouterr().out
    assert "https://recordbench.example.test:8443/auth/login" in output
    assert "Initial administrator username: alice.admin" in output
    assert "prepared: complete" in output and "running: not verified" in output
    assert "Browser sign-in: not verified" in output and "ACCESS GRANTED" not in output
    assert "'" + str(root) + "' --resume" in output
    assert all(path.read_text().strip() not in output for path in paths["secrets"].iterdir() if path.is_file())
    receipt = root / "state/install-progress.json"
    assert receipt.stat().st_mode & 0o777 == 0o600
    value = json.loads(receipt.read_text())
    assert value["format_version"] == 1
    assert "alice.admin" not in receipt.read_text()


@pytest.mark.parametrize("interrupted_after", ["configuration", "administrator", "models"])
def test_resume_keeps_identity_sources_secrets_and_verified_models(tmp_path, monkeypatch, interrupted_after):
    root, args, paths = configured_node(tmp_path)
    installation = json.loads((root / "installation.json").read_text())
    installation["models"] = "review"
    (root / "installation.json").write_text(json.dumps(installation))
    args.models = "review"
    counts = {"account": 0, "stage": 0, "storage": 0}
    repository = LocalAccountRepository(paths["accounts"] / "local-accounts.json")
    model = paths["models"] / "synthetic-pinned-model"
    source = paths["storage"] / "synthetic-source.txt"
    secrets_before = {p.name: p.read_bytes() for p in paths["secrets"].iterdir() if p.is_file()}
    monkeypatch.setattr(installer, "_password", lambda args: PASSWORD)
    monkeypatch.setattr(installer, "_preflight", lambda *a, **kw: ())
    def command(console, command, **kwargs):
        if "accounts" in command and "init" in command:
            counts["account"] += 1
            repository.initialize("alice.admin", "Alice Administrator", PASSWORD, actor="synthetic-operator")
        elif "accounts" in command and "list" in command:
            assert repository.read()["alice.admin"].enabled
        elif "storage" in command and "init" in command:
            counts["storage"] += 1
            (paths["storage"] / ".recordbench-managed-storage.json").write_text("synthetic marker")
            source.write_text("synthetic source remains intact")
        elif "storage" in command and "status" in command:
            assert source.read_text() == "synthetic source remains intact"
        elif "model-stager" in command and "verify" in command:
            return subprocess.CompletedProcess(command, 0 if model.exists() else 1, "", "")
        elif "model-stager" in command and "stage" in command:
            counts["stage"] += 1
            model.write_text("synthetic pinned model")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(installer, "_run", command)
    phase = installer._install_phase
    def interrupt(root, name, state):
        phase(root, name, state)
        if name == interrupted_after and state == "complete":
            raise RuntimeError("synthetic interruption")
    if interrupted_after != "configuration":
        monkeypatch.setattr(installer, "_install_phase", interrupt)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            installer._provision(installer.Console(color=False), args, root, "local", "review", "alice.admin", "Alice Administrator")
    before_account = repository.path.read_bytes() if repository.path.exists() else None
    monkeypatch.setattr(installer, "_install_phase", phase)
    resumed = installer._parser().parse_args(["install", "--resume", "--prepare-only", "--non-interactive"])
    installer._resume_node(installer.Console(color=False), resumed, root)
    after_account = repository.path.read_bytes()
    if before_account is not None:
        assert after_account == before_account
    installer._resume_node(installer.Console(color=False), resumed, root)
    assert repository.path.read_bytes() == after_account
    assert counts == {"account": 1, "stage": 1, "storage": 1}
    assert source.read_text() == "synthetic source remains intact"
    assert {p.name: p.read_bytes() for p in paths["secrets"].iterdir() if p.is_file()} == secrets_before
    assert installer._install_progress(root)["phases"]["prepared"] == "complete"


def test_health_records_useful_cpu_capability_without_claiming_failed_model_ready(tmp_path, monkeypatch):
    root, _, _ = configured_node(tmp_path)
    installation = json.loads((root / "installation.json").read_text())
    installation["models"] = "review"
    (root / "installation.json").write_text(json.dumps(installation))
    payload = {"product": "RecordBench", "status": "degraded", "storage": {"status": "ready"},
        "capabilities": {"source_review": "ready", "malware_scan": "ready", "answering": "temporarily unavailable", "search": "word search only"}}
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr(installer, "_login_reachable", lambda root: True)
    clock = iter([0, 0, 1, 2, 901])
    monkeypatch.setattr(installer.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(installer.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="selected capabilities"):
        installer._wait_health(installer.Console(color=False), root)
    phases = installer._install_progress(root)["phases"]
    assert phases["running"] == phases["basic_review"] == phases["login_reachable"] == "complete"
    assert phases["selected_capabilities"] == "incomplete"


def test_model_resume_receipt_verifies_exact_bytes_without_network_or_writes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("synthetic_model_stager", ROOT / "scripts/stage-models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "models": [{"revision": "a" * 40, "license": "Apache-2.0"}]}))
    root = tmp_path / "models"
    root.mkdir()
    artifact = root / "synthetic-model.bin"
    artifact.write_bytes(b"synthetic pinned artifact")
    groups = frozenset({"review"})
    module._stage_receipt(root, catalog, groups, "portable", [artifact])
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("verification must stay offline"))
    module._verify_stage(root, catalog, groups, "portable")
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()} == before
    artifact.write_bytes(b"synthetic changed artifact")
    with pytest.raises(RuntimeError, match="missing or changed"):
        module._verify_stage(root, catalog, groups, "portable")
    with pytest.raises(RuntimeError, match="selection changed"):
        module._verify_stage(root, catalog, groups, "quality")
