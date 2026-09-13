from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import recordbench_antivirus as antivirus
import recordbench_install as installer


def cvd_header(epoch=None):
    epoch = int(time.time()) if epoch is None else epoch
    # Intentionally unsigned synthetic test data; never passes real sigtool.
    return f"ClamAV-VDB:Synthetic-date:1:1:1:synthetic:unsigned:synthetic:{epoch}".encode().ljust(512, b" ") + b"synthetic database"


@pytest.mark.parametrize("mirror,proxy", [(None, None), ("https://mirror.example.test/signatures", None),
    (None, "http://proxy.example.test:3128"), ("http://mirror.example.test:8080", "http://[::1]:3128")])
def test_configuration_roundtrip_is_canonical_and_never_disables_verification(tmp_path, mirror, proxy):
    root = tmp_path / "node"
    (root / "config").mkdir(parents=True, mode=0o700)
    path = root / "config" / antivirus.CONFIG_NAME
    text = antivirus.configuration(mirror, proxy)
    path.write_text(text)
    path.chmod(0o600)
    antivirus.validate_saved(root, {antivirus.CONFIG_KEY: str(path)}, installer)
    assert "TestDatabases yes" in text
    assert ("PrivateMirror" in text) == bool(mirror)
    assert "Password" not in text


@pytest.mark.parametrize("selection", [
    ["--antivirus-mirror", "https://mirror.example.test/signatures"],
    ["--antivirus-proxy", "http://proxy.example.test:3128"],
    ["--antivirus-mirror", "https://mirror.example.test/signatures",
     "--antivirus-proxy", "http://proxy.example.test:3128"],
    ["--reset-antivirus"],
])
@pytest.mark.parametrize("existing", [False, True])
def test_configuration_command_persists_selection_for_resume(tmp_path, monkeypatch, selection, existing):
    root = tmp_path / "synthetic node"
    (root / "config").mkdir(parents=True, mode=0o700)
    (root / "state").mkdir(mode=0o700)
    environment = root / "compose.env"
    environment.write_text('COMPOSE_PROJECT_NAME="synthetic"\n' + (
        f'{antivirus.CONFIG_KEY}="old-selection"\n' if existing else ""))
    environment.chmod(0o600)
    args = installer._parser().parse_args(["antivirus", "--root", str(root), *selection])
    monkeypatch.setattr(installer, "_saved_node_arguments", lambda *a, **kw: ({"profiles": []}, ROOT))
    monkeypatch.setattr(installer, "_compose", lambda *a, **kw: ["docker", "compose"])
    monkeypatch.setattr(installer, "_run", lambda *a, **kw: SimpleNamespace(stdout='[{"State": "exited"}]'))

    antivirus.run(installer.Console(color=False, quiet=True), args, root, installer)

    saved = installer._dotenv(environment)
    path = root / "config" / antivirus.CONFIG_NAME
    assert saved == {"COMPOSE_PROJECT_NAME": "synthetic", antivirus.CONFIG_KEY: str(path)}
    assert path.read_text() == antivirus.configuration(args.antivirus_mirror, args.antivirus_proxy)
    assert path.stat().st_mode & 0o777 == 0o600
    assert environment.stat().st_mode & 0o777 == 0o600
    antivirus.validate_saved(root, saved, installer)


@pytest.mark.parametrize("value", ["https://user:password@mirror.example.test", "https://mirror.example.test\nOnUpdateExecute bad",
    "file:///tmp/source", "https://mirror.example.test/#bad", "https://mirror.example.test/?token=bad", "https://mirror.example.test/$(bad)",
    "https://mirror.example.test:65536", "http://mirror.example.test\\bad"])
def test_network_configuration_rejects_credentials_and_directive_injection(value):
    with pytest.raises(RuntimeError):
        antivirus.configuration(value, None)


def test_saved_configuration_cannot_add_executable_directives(tmp_path):
    root = tmp_path / "node"
    (root / "config").mkdir(parents=True)
    path = root / "config" / antivirus.CONFIG_NAME
    path.write_text(antivirus.configuration(None, None) + "OnUpdateExecute synthetic-command\n")
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match="unsupported directives"):
        antivirus.validate_saved(root, {antivirus.CONFIG_KEY: str(path)}, installer)


@pytest.mark.parametrize("age,expected", [(0, 0), (72 * 3600 + 60, 1), (-600, 1)])
def test_signature_health_uses_database_age_not_mtime(tmp_path, age, expected):
    (tmp_path / "main.cvd").write_bytes(cvd_header())
    daily = tmp_path / "daily.cvd"
    daily.write_bytes(cvd_header(int(time.time()) - age))
    os.utime(daily, None)  # Copying/touching old databases cannot make them fresh.
    result = subprocess.run(["sh", str(ROOT / "deploy/clamav/signature-health.sh")],
        env={**os.environ, "RECORDBENCH_SIGNATURE_DIR": str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode == expected


def test_incomplete_import_blocks_health_even_with_fresh_databases(tmp_path):
    for name in antivirus.DATABASES:
        (tmp_path / name).write_bytes(cvd_header())
    (tmp_path / ".recordbench-import-pending").touch()
    result = subprocess.run(["sh", str(ROOT / "deploy/clamav/signature-health.sh")],
        env={**os.environ, "RECORDBENCH_SIGNATURE_DIR": str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout.strip() == "signature-import-incomplete"


@pytest.mark.parametrize("problem", ["symlink", "ancestor-symlink", "stale", "writable", "missing", "invalid"])
def test_import_snapshot_refuses_unsafe_or_stale_sources(tmp_path, problem):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    for name in antivirus.DATABASES:
        (source / name).write_bytes(cvd_header())
        (source / name).chmod(0o600)
    daily = source / "daily.cvd"
    if problem == "symlink":
        daily.unlink()
        daily.symlink_to(source / "main.cvd")
    elif problem == "ancestor-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / "source"
    elif problem == "stale":
        daily.write_bytes(cvd_header(int(time.time()) - 300000))
    elif problem == "writable":
        daily.chmod(0o666)
    elif problem == "missing":
        daily.unlink()
    else:
        daily.write_bytes(b"invalid" * 100)
    with pytest.raises((RuntimeError, OSError)):
        antivirus._snapshot(source, target, installer)


def test_snapshot_preserves_bytes_without_claiming_signature_authenticity(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    for name in antivirus.DATABASES:
        (source / name).write_bytes(cvd_header())
    antivirus._snapshot(source, target, installer)
    assert all((source / name).read_bytes() == (target / name).read_bytes() for name in antivirus.DATABASES)


def test_import_verification_failure_preserves_existing_databases(tmp_path):
    source, database, tools = (tmp_path / name for name in ("source", "database", "tools"))
    for directory in (source, database, tools):
        directory.mkdir()
    for name in antivirus.DATABASES:
        (source / name).write_bytes(cvd_header())
        (database / name).write_bytes(b"previous synthetic database")
    sigtool = tools / "sigtool"
    sigtool.write_text("#!/bin/sh\nexit 1\n")
    sigtool.chmod(0o755)
    result = subprocess.run(["sh", str(ROOT / "deploy/clamav/import-signatures.sh")], env={**os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"], "RECORDBENCH_SIGNATURE_SOURCE": str(source),
        "RECORDBENCH_SIGNATURE_DIR": str(database), "RECORDBENCH_ANTIVIRUS_HELPERS": str(ROOT / "deploy/clamav")},
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "signature-import-verification-failed" in result.stdout
    assert all((database / name).read_bytes() == b"previous synthetic database" for name in antivirus.DATABASES)
    assert not (database / ".recordbench-import-pending").exists()


def test_startup_wait_is_bounded_and_does_not_echo_updater_logs(monkeypatch):
    ticks = iter([0, 1, 181])
    monkeypatch.setattr(antivirus.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(antivirus.time, "sleep", lambda _: None)
    commands = []
    def probe(command):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, "403 synthetic-private-log", "")
    fake = SimpleNamespace(_run=lambda *a, **kw: None, _probe=probe)
    with pytest.raises(RuntimeError, match="blocked") as raised:
        antivirus._prepare_locked(installer.Console(color=False, quiet=True), Path("/synthetic"), ["docker", "compose"], fake)
    assert "synthetic-private-log" not in str(raised.value)
    assert "ANTIVIRUS_RECOVERY.md" in str(raised.value)
    assert len(commands) == 2


def test_startup_accepts_only_positive_fixed_signature_result():
    calls = []
    def probe(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "signatures-fresh\n", "")
    antivirus._prepare_locked(installer.Console(color=False, quiet=True), Path("/synthetic"), ["docker", "compose"],
        SimpleNamespace(_run=lambda *a, **kw: None, _probe=probe))
    assert len(calls) == 1


@pytest.mark.parametrize("state", ["running", "restarting", "paused", "dead", "unknown"])
def test_configure_and_import_refuse_active_or_unknown_node_states(tmp_path, monkeypatch, state):
    (tmp_path / "state").mkdir(mode=0o700)
    args = installer._parser().parse_args(["antivirus", "--root", str(tmp_path), "--antivirus-mirror", "https://mirror.example.test"])
    monkeypatch.setattr(installer, "_saved_node_arguments", lambda *a, **kw: ({"profiles": []}, ROOT))
    monkeypatch.setattr(installer, "_compose", lambda *a, **kw: ["docker", "compose"])
    monkeypatch.setattr(installer, "_run", lambda *a, **kw: SimpleNamespace(stdout='[{"State": "' + state + '"}]'))
    monkeypatch.setattr(installer, "_atomic_private_write", lambda *a: pytest.fail("running node was modified"))
    with pytest.raises(RuntimeError, match="stop this node"):
        antivirus.run(installer.Console(color=False, quiet=True), args, tmp_path, installer)


def test_legacy_capsule_retains_its_startup_without_missing_helper_probe(tmp_path):
    commands = []
    antivirus.prepare(installer.Console(color=False, quiet=True), tmp_path,
        ["docker", "compose", "-f", str(tmp_path / "compose.yaml")],
        SimpleNamespace(_run=lambda *a, **kw: commands.append(a)))
    assert commands == []


def test_antivirus_operation_lock_blocks_concurrent_preparation_and_recovery(tmp_path):
    (tmp_path / "state").mkdir(mode=0o700)
    with antivirus._operation_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another antivirus"):
            with antivirus._operation_lock(tmp_path):
                pytest.fail("concurrent operation entered")


def test_pending_import_marker_is_durable_before_first_replacement():
    script = (ROOT / "deploy/clamav/import-signatures.sh").read_text()
    marker = script.index('touch "$database/.recordbench-import-pending"')
    assert marker < script.index("\nsync\n", marker) < script.index("mv -f", marker)


def test_antivirus_flags_cannot_silently_change_install_or_resume(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/recordbench_install.py"), "install",
        "--root", str(tmp_path / "new"), "--antivirus-mirror", "https://mirror.example.test"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "require the antivirus command" in result.stderr
    assert not (tmp_path / "new").exists()
