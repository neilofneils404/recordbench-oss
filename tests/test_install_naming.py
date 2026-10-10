"""Synthetic naming-generation compatibility, without installing a host node."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_oss_installer import installer, ROOT
from tests.test_first_run_handoff import configured_node


@pytest.fixture(autouse=True)
def no_host_account(monkeypatch):
    monkeypatch.setattr(installer, "_legacy_account", lambda: False)


def test_fresh_defaults_and_generated_coordinates(tmp_path):
    args = installer._parser().parse_args([])
    assert installer._select_names(args, tmp_path / "fresh") == "exculpata"
    assert installer._default_root() == Path("/srv/exculpata")
    root, _, paths = configured_node(tmp_path, names="exculpata")
    env = installer._dotenv(root / "compose.env")
    expected = f"exculpata-{installer.hashlib_short(root)}"
    assert env["EXCULPATA_COMPOSE_PROJECT"] == env["EXCULPATA_IMAGE_NAMESPACE"] == expected
    assert env["EXCULPATA_APP_ENV_FILE"] == "exculpata.env"
    assert env["EXCULPATA_STORAGE_NAMES"] == "exculpata"
    assert not any(key.startswith("RECORDBENCH_") for key in env)
    assert (paths["config"] / "exculpata.env").is_file()
    assert not (paths["config"] / "recordbench.env").exists()
    assert "dbname=recordbench user=recordbench" in (paths["secrets"] / "postgres-dsn").read_text()
    assert installer._node_names(root) == "exculpata"


@pytest.mark.parametrize("signal", ["config", "marker", "external-marker", "account"])
def test_legacy_signals_keep_names_and_refuse_migration(tmp_path, monkeypatch, signal):
    root = tmp_path / "legacy"
    storage = tmp_path / "storage"
    args = installer._parser().parse_args(["--root", str(root), "--storage-root", str(storage)])
    if signal == "config":
        (root / "config").mkdir(parents=True)
        (root / "config/recordbench.env").write_text("# Synthetic retained configuration\n")
    elif signal in {"marker", "external-marker"}:
        target = root if signal == "marker" else storage
        target.mkdir()
        (target / ".recordbench-managed-storage.json").write_text("{}")
    else:
        monkeypatch.setattr(installer, "_legacy_account", lambda: True)
        assert installer._default_root() == Path("/srv/recordbench")
    assert installer._select_names(args, root) == "recordbench"
    args.names = "exculpata"
    with pytest.raises(installer.NamingError, match="migration.*not implemented"):
        installer._select_names(args, root)


@pytest.mark.parametrize("command", ["install", "preflight", "doctor", "update", "backup", "restore"])
def test_explicit_rename_is_refused_before_any_write(tmp_path, monkeypatch, capsys, command):
    root = tmp_path / "legacy"
    (root / "config").mkdir(parents=True)
    retained = root / "config/recordbench.env"
    retained.write_bytes(b"# Synthetic operator formatting\r\n")
    monkeypatch.setattr(sys, "argv", ["install", command, "--root", str(root), "--names", "exculpata", "--non-interactive"])
    monkeypatch.setattr(installer, "_run", lambda *a, **k: pytest.fail("external command before rename refusal"))
    assert installer.main() == 1
    assert "migration, which is not implemented" in capsys.readouterr().out
    assert retained.read_bytes() == b"# Synthetic operator formatting\r\n"
    assert [p.relative_to(root) for p in root.rglob("*") if p.is_file()] == [Path("config/recordbench.env")]


def test_legacy_reconfiguration_preserves_all_config_bytes_and_namespace(tmp_path):
    root, args, paths = configured_node(tmp_path)
    compose = root / "compose.env"
    installer._replace_env(compose, "RECORDBENCH_COMPOSE_PROJECT", "synthetic-original-project")
    installer._replace_env(compose, "RECORDBENCH_IMAGE_NAMESPACE", "synthetic-original-images")
    controls = [compose, paths["config"] / "recordbench.env", paths["config"] / "transcription.env"]
    for path in controls:
        path.write_bytes(b"# Synthetic operator note\r\n" + path.read_bytes().replace(b"\n", b"\r\n"))
    before = {path: path.read_bytes() for path in controls}
    installer._configure(installer.Console(color=False, quiet=True), args, root, paths, "synthetic-release", ROOT, ())
    assert {path: path.read_bytes() for path in controls} == before
    assert all(b"EXCULPATA_" not in content for content in before.values())
    assert not (paths["config"] / "exculpata.env").exists()


@pytest.mark.parametrize("names", ["recordbench", "exculpata"])
def test_doctor_and_scheduled_units_follow_installed_generation(tmp_path, monkeypatch, capsys, names):
    root, args, _ = configured_node(tmp_path, names=names)
    args.dry_run = True
    monkeypatch.setattr(installer, "_run", lambda *a, **k: None)
    installer._doctor(installer.Console(color=False), args, root)
    assert f"naming generation :: {names}" in capsys.readouterr().out
    home = tmp_path / "synthetic-home"
    monkeypatch.setattr(Path, "home", lambda: home)
    installer._schedule_backup(installer.Console(color=False), root, dry_run=False)
    record = json.loads((root / "state/backup-unit.json").read_text())
    assert record["service"] == f"{names}-backup-{installer.hashlib_short(root)}.service"
    units = home / ".config/systemd/user"
    assert (units / record["service"]).is_file()
    assert f"Unit={record['service']}" in (units / record["timer"]).read_text()
    other = "exculpata" if names == "recordbench" else "recordbench"
    assert not list(units.glob(f"{other}-*"))


@pytest.mark.parametrize("names", ["recordbench", "exculpata"])
def test_shell_cannot_override_saved_naming_coordinates(tmp_path, names):
    root, _, _ = configured_node(tmp_path, names=names)
    command = installer._compose(root, (), release=ROOT, auth="local")
    env = installer._compose_environment(command, {
        "EXCULPATA_IMAGE_NAMESPACE": "synthetic-unrelated-images",
        "RECORDBENCH_IMAGE_NAMESPACE": "synthetic-other-images",
        "EXCULPATA_APP_ENV_FILE": "unrelated.env",
        "EXCULPATA_STORAGE_NAMES": "unrelated",
        "COMPOSE_PROJECT_NAME": "synthetic-unrelated-project",
    })
    assert env["EXCULPATA_IMAGE_NAMESPACE"] == f"{names}-{installer.hashlib_short(root)}"
    assert env["EXCULPATA_COMPOSE_PROJECT"] == f"{names}-{installer.hashlib_short(root)}"
    assert "COMPOSE_PROJECT_NAME" not in env
    assert "EXCULPATA_APP_ENV_FILE" not in env


@pytest.mark.parametrize("names", ["recordbench", "exculpata"])
def test_compose_renders_saved_names_database_and_marker_mode(tmp_path, names):
    root, _, _ = configured_node(tmp_path, names=names)
    command = installer._compose(root, ("tools",), release=ROOT, auth="local")
    result = subprocess.run([*command, "config", "--format", "json"], env=installer._compose_environment(command), capture_output=True, text=True, check=True)
    graph = json.loads(result.stdout)
    expected = f"{names}-{installer.hashlib_short(root)}"
    assert graph["name"] == expected
    assert graph["services"]["app"]["image"].startswith(expected + "/")
    assert graph["services"]["postgres"]["environment"]["POSTGRES_DB"] == "recordbench"
    assert graph["services"]["postgres"]["environment"]["POSTGRES_USER"] == "recordbench"
    assert graph["services"]["account-admin"]["environment"]["EXCULPATA_STORAGE_NAMES"] == names


def test_legacy_installer_import_and_both_entrypoints():
    import exculpata_install
    import recordbench_install
    assert exculpata_install is recordbench_install
    for script in ("exculpata_install.py", "recordbench_install.py"):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--help"], capture_output=True, text=True)
        assert result.returncode == 0 and "--names" in result.stdout


def test_old_missing_project_defaults_remain_old_without_editing_env(tmp_path):
    root, _, _ = configured_node(tmp_path)
    path = root / "compose.env"
    original = b"".join(line for line in path.read_bytes().splitlines(keepends=True)
                        if not line.startswith((b"RECORDBENCH_COMPOSE_PROJECT=", b"RECORDBENCH_IMAGE_NAMESPACE=")))
    path.write_bytes(original)
    env = installer._compose_environment(installer._compose(root, ()), {
        "EXCULPATA_STORAGE_ROOT": "synthetic-unrelated-storage",
        "RECORDBENCH_STORAGE_ROOT": "synthetic-other-storage",
    })
    assert env["EXCULPATA_IMAGE_NAMESPACE"] == "recordbench"
    assert env["EXCULPATA_COMPOSE_PROJECT"] == "recordbench"
    assert "EXCULPATA_STORAGE_ROOT" not in env and "RECORDBENCH_STORAGE_ROOT" not in env
    assert path.read_bytes() == original


@pytest.mark.parametrize("names", ["recordbench", "exculpata"])
def test_update_retains_generation_and_config_except_release(tmp_path, monkeypatch, names):
    root, _, paths = configured_node(tmp_path, names=names)
    controls = [root / "compose.env", paths["config"] / f"{names}.env", paths["config"] / "transcription.env"]
    before = {path: path.read_bytes() for path in controls}
    calls = []
    monkeypatch.setattr(installer, "_preflight", lambda *a, **k: ())
    monkeypatch.setattr(installer, "_stage_release", lambda *a, **k: ("synthetic-next", ROOT))
    monkeypatch.setattr(installer, "_run", lambda console, command, **k: calls.append(command))
    monkeypatch.setattr(installer, "_wait_health", lambda *a: None)
    monkeypatch.setattr(installer, "_seal_provisioning", lambda *a: None)
    args = installer._parser().parse_args(["update", "--root", str(root), "--no-backup", "--non-interactive"])
    installer._update(installer.Console(color=False, quiet=True), args, root)
    for path in controls:
        expected = before[path]
        if path.name == "compose.env":
            expected = expected.replace(b'RELEASE_ID="synthetic-release"', b'RELEASE_ID="synthetic-next"')
        assert path.read_bytes() == expected
    assert installer._node_names(root) == names
    assert any("up" in call for call in calls)
    assert not (paths["config"] / ("exculpata.env" if names == "recordbench" else "recordbench.env")).exists()
