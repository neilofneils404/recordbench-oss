"""Synthetic split-filesystem backup boundaries; no running services needed."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import recordbench_backup as backup  # noqa: E402


def _private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _version(path: Path) -> str:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return connection.execute("SELECT version FROM synthetic_state").fetchone()[0]
    finally:
        connection.close()


class SyntheticNode:
    def __init__(self, root: Path, monkeypatch, *, wal: bool = False):
        self.root = root
        self.node = root / "node"
        self.storage = root / "separate-storage"
        self.archive = root / "archive"
        self.events: list[str] = []
        self.corrupt_at_stop = False
        self.fail_dump = False
        self.projected_version = "initial"
        self.connections = []
        for name in ("runtime", "config", "secrets", "state"):
            (self.node / name).mkdir(parents=True, exist_ok=True)
        self.storage.mkdir()
        (self.storage / ".recordbench-managed-storage.json").write_text("{}")
        repository = root / "repository"
        repository.mkdir()
        (repository / "config").write_text("synthetic repository stub")
        _private_json(self.node / "installation.json", {
            "format_version": 1, "auth": "local", "profiles": [],
            "release_path": str(ROOT), "release_id": "synthetic-release",
            "node_id": "synthetic-node",
        })
        _private_json(self.node / "config/backup.json", {
            "format_version": 1, "repository": str(repository),
            "recovery_key_output": str(root / "recovery-key"), "retention": "14d",
        })
        environment = {
            "RECORDBENCH_RUNTIME_ROOT": str(self.node / "runtime"),
            "RECORDBENCH_CONFIG_ROOT": str(self.node / "config"),
            "RECORDBENCH_SECRETS_ROOT": str(self.node / "secrets"),
            "RECORDBENCH_STORAGE_ROOT": str(self.storage),
        }
        env = self.node / "compose.env"
        env.write_text("".join(f"{key}={json.dumps(value)}\n" for key, value in environment.items()))
        env.chmod(0o600)
        password = self.node / "secrets/restic-password"
        password.write_text("synthetic credential for a mocked repository")
        password.chmod(0o600)
        self.control = self.node / "runtime/workbench.sqlite"
        self.registry = self.storage / "matters/synthetic-matter/sources/source-registry.sqlite3"
        for path in (self.control, self.registry):
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            if wal and path == self.control:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE synthetic_state(version TEXT NOT NULL)")
            connection.execute("INSERT INTO synthetic_state VALUES ('initial')")
            connection.commit()
            self.connections.append(connection)
        self.original_run = backup._run
        monkeypatch.setattr(backup, "_run", self.run)
        monkeypatch.setattr(backup, "_restic", self.restic)
        monkeypatch.setattr(backup, "_running_services", lambda _: frozenset({"app", "gateway"}))
        monkeypatch.setattr(backup, "_health", lambda _: {
            "product": "RecordBench",
            **{key: {"queued": 0, "running": 0} for key in backup.ACTIVE_JOB_KEYS},
        })

    def close(self):
        for connection in self.connections:
            connection.close()

    def run(self, command, **kwargs):
        if command[0] == "cp":
            return self.original_run(command, **kwargs)
        if "stop" in command:
            self.events.append("stop")
            # A request admitted after the initial health probe finishes at stop.
            for connection in self.connections:
                connection.execute("UPDATE synthetic_state SET version='frozen'")
                connection.commit()
            self.projected_version = "frozen"
            if self.corrupt_at_stop:
                self.connections[1].close()
                self.registry.write_bytes(b"synthetic damaged database")
        elif "up" in command:
            self.events.append("restart")
            for index, connection in enumerate(self.connections):
                if self.corrupt_at_stop and index == 1:
                    continue
                connection.execute("UPDATE synthetic_state SET version='live'")
                connection.commit()
        elif "pg_dump" in command:
            self.events.append("dump")
            if self.fail_dump:
                raise backup.BackupError("synthetic projection failure")
            return subprocess.CompletedProcess(command, 0, self.projected_version.encode())
        elif "pg_restore" not in command:
            raise AssertionError("unexpected external command")
        return subprocess.CompletedProcess(command, 0, b"")

    def restic(self, config, password, arguments, **kwargs):
        arguments = tuple(arguments)
        action = arguments[0]
        if action == "backup":
            self.events.append("transfer")
            payload, storage = map(Path, arguments[-2:])
            assert storage not in payload.parents and payload not in storage.parents
            shutil.copytree(payload, self.archive / "payload")
            shutil.copytree(storage, self.archive / "managed-storage", symlinks=True)
            output = json.dumps({"message_type": "summary", "snapshot_id": "a" * 64}).encode()
            return subprocess.CompletedProcess(arguments, 0, output)
        if action == "restore":
            target = Path(arguments[arguments.index("--target") + 1])
            shutil.copytree(self.archive, target, dirs_exist_ok=True, symlinks=True)
        return subprocess.CompletedProcess(arguments, 0, b"")

    def backup(self):
        return backup.backup(argparse.Namespace(node_root=self.node, dry_run=False))

    def restore(self):
        return backup.restore(argparse.Namespace(
            node_root=self.node, target=self.root / "restored", snapshot="a" * 64,
        ))


@pytest.fixture
def node_factory(tmp_path, monkeypatch):
    nodes = []

    def create(**kwargs):
        node = SyntheticNode(tmp_path, monkeypatch, **kwargs)
        nodes.append(node)
        return node

    yield create
    for node in nodes:
        node.close()


def test_managed_registry_is_frozen_before_restart(node_factory):
    node = node_factory()
    assert node.backup() == 0
    restored_registry = node.archive / "managed-storage" / node.registry.relative_to(node.storage)
    assert _version(node.registry) == "live"
    assert _version(restored_registry) == "frozen"
    assert node.events.index("restart") < node.events.index("transfer")
    assert not list(node.node.glob(".recordbench-backup-snapshot-*"))
    assert not list(node.storage.parent.glob(".recordbench-storage-snapshot-*"))


def test_wal_control_is_consolidated_before_restart(node_factory):
    node = node_factory(wal=True)
    assert node.backup() == 0
    frozen = node.archive / "payload/runtime/workbench.sqlite"
    assert _version(node.control) == "live"
    assert _version(frozen) == "frozen"
    assert not frozen.with_name(frozen.name + "-wal").exists()
    assert not frozen.with_name(frozen.name + "-shm").exists()


def test_projection_and_stores_share_the_stopped_boundary(node_factory):
    node = node_factory()
    assert node.backup() == 0
    assert (node.archive / "payload/postgres/review-index.dump").read_text() == "frozen"
    assert node.events.index("stop") < node.events.index("dump") < node.events.index("restart")


def test_corrupt_managed_registry_refuses_backup_and_restarts_app(node_factory):
    node = node_factory()
    node.corrupt_at_stop = True
    with pytest.raises(backup.BackupError, match="SQLite"):
        node.backup()
    assert node.events.count("restart") == 1
    assert "transfer" not in node.events
    assert json.loads((node.node / "state/backup-status.json").read_text())["state"] == "failed"
    assert not list(node.node.glob(".recordbench-backup-snapshot-*"))
    assert not list(node.storage.parent.glob(".recordbench-storage-snapshot-*"))


def test_restore_validates_the_managed_registry(node_factory):
    node = node_factory()
    assert node.backup() == 0
    registry = node.archive / "managed-storage" / node.registry.relative_to(node.storage)
    registry.write_bytes(b"synthetic damaged restored registry")
    with pytest.raises(backup.BackupError, match="SQLite"):
        node.restore()
    assert not (node.root / "restored/RESTORE_DRILL_VERIFIED.json").exists()
    assert node.events.count("restart") == 1


def test_restore_requires_managed_storage_boundary(node_factory):
    node = node_factory()
    assert node.backup() == 0
    shutil.rmtree(node.archive / "managed-storage")
    with pytest.raises(backup.BackupError, match="managed storage"):
        node.restore()
    assert not (node.root / "restored/RESTORE_DRILL_VERIFIED.json").exists()


def test_restore_detects_missing_registry_even_with_storage_marker(node_factory):
    node = node_factory()
    assert node.backup() == 0
    (node.archive / "managed-storage" / node.registry.relative_to(node.storage)).unlink()
    with pytest.raises(backup.BackupError, match="SQLite inventory"):
        node.restore()


def test_restore_receipt_counts_control_and_managed_stores(node_factory):
    node = node_factory(wal=True)
    assert node.backup() == 0
    assert node.restore() == 0
    target = node.root / "restored"
    receipt = json.loads((target / "RESTORE_DRILL_VERIFIED.json").read_text())
    assert receipt["sqlite_stores"] == 2
    assert receipt["managed_sqlite_stores"] == 1
    assert _version(target / "payload/runtime/workbench.sqlite") == "frozen"
    assert _version(target / "managed-storage" / node.registry.relative_to(node.storage)) == "frozen"
    assert _version(node.control) == "live"
    assert _version(node.registry) == "live"


def test_active_work_still_defers_without_stopping_services(node_factory, monkeypatch):
    node = node_factory()
    monkeypatch.setattr(backup, "_health", lambda _: {
        "product": "RecordBench",
        **{key: {"queued": int(key == "research_jobs"), "running": 0} for key in backup.ACTIVE_JOB_KEYS},
    })
    assert node.backup() == 0
    assert node.events == []
    assert json.loads((node.node / "state/backup-status.json").read_text())["state"] == "deferred"


def test_stopped_projection_failure_restarts_and_cleans_up(node_factory):
    node = node_factory()
    node.fail_dump = True
    with pytest.raises(backup.BackupError, match="synthetic projection failure"):
        node.backup()
    assert node.events == ["stop", "dump", "restart"]
    assert not list(node.node.glob(".recordbench-backup-snapshot-*"))
    assert not list(node.storage.parent.glob(".recordbench-storage-snapshot-*"))


def test_snapshot_does_not_follow_managed_symlinks(node_factory):
    node = node_factory()
    outside = node.root / "outside.sqlite"
    outside.write_bytes(b"synthetic external original")
    (node.storage / "linked.sqlite").symlink_to(outside)
    with pytest.raises(backup.BackupError, match="symbolic link"):
        node.backup()
    assert outside.read_bytes() == b"synthetic external original"
    assert "transfer" not in node.events
    assert node.events.count("restart") == 1


@pytest.mark.skipif(
    os.environ.get("RECORDBENCH_BACKUP_INTEGRATION") != "1",
    reason="opt-in synthetic restic/PostgreSQL drill",
)
def test_encrypted_split_snapshot_and_postgres_restore(node_factory, monkeypatch):
    """Real repository and dump/import; simulated app stop/restart only.

    Requires restic and an already installed pgvector image. No image pull,
    published port, live volume, or existing service is used.
    """
    assert shutil.which("restic") and shutil.which("docker")
    original_restic = backup._restic
    node = node_factory(wal=True)
    monkeypatch.setattr(backup, "_restic", original_restic)
    config = backup._backup_config(node.node)
    password = node.node / "secrets/restic-password"
    (Path(config["repository"]) / "config").unlink()  # Replace the fixture stub only.
    original_restic(config, password, ("init", "--repository-version", "2"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    image = subprocess.run(
        ["docker", "image", "inspect", backup.POSTGRES_IMAGE, "--format", "{{.Id}}"],
        capture_output=True, check=True, text=True,
    ).stdout.strip()
    container = subprocess.run([
        "docker", "run", "--detach", "--rm", "--pull=never", "--network", "none",
        "--read-only", "--log-driver", "none", "--memory", "512m", "--cpus", "1",
        "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=256m",
        "--tmpfs", "/var/run/postgresql:rw,nosuid,nodev,size=16m",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=recordbench",
        "-e", "POSTGRES_DB=recordbench", image, "postgres", "-c", "listen_addresses=",
    ], capture_output=True, check=True, text=True).stdout.strip()

    def execute(*command, input_bytes=None):
        return subprocess.run(
            ["docker", "exec", "-i", container, *command], input=input_bytes,
            capture_output=True, check=True, timeout=30,
        )

    def sql(statement, database="recordbench"):
        return execute(
            "psql", "-X", "-U", "recordbench", "-d", database, "-v", "ON_ERROR_STOP=1", "-At",
            input_bytes=statement.encode(),
        ).stdout.decode().strip()

    try:
        for attempt in range(60):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "recordbench"],
                capture_output=True, timeout=10,
            )
            main_process = subprocess.run(
                ["docker", "exec", container, "cat", "/proc/1/comm"],
                capture_output=True, timeout=10,
            )
            if ready.returncode == 0 and main_process.stdout.strip() == b"postgres":
                break
            time.sleep(0.5)
        else:
            pytest.fail("isolated PostgreSQL did not become ready")
        sql("CREATE TABLE synthetic_state(version text); INSERT INTO synthetic_state VALUES ('initial');")

        def commands(command, **kwargs):
            if "pg_dump" in command:
                node.events.append("dump")
                return execute("pg_dump", "-U", "recordbench", "-d", "recordbench", "--format=custom")
            if "pg_restore" in command:
                return execute("pg_restore", "--list", input_bytes=kwargs["input_bytes"])
            result = node.run(command, **kwargs)
            if "stop" in command:
                sql("UPDATE synthetic_state SET version='frozen';")
            elif "up" in command:
                sql("UPDATE synthetic_state SET version='live';")
            return result

        monkeypatch.setattr(backup, "_run", commands)
        assert node.backup() == 0
        original_restic(config, password, ("check", "--read-data"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receipt = json.loads((node.node / "state/backup-status.json").read_text())
        target = node.root / "restored"
        assert backup.restore(argparse.Namespace(
            node_root=node.node, target=target, snapshot=receipt["snapshot_id"],
        )) == 0
        files = backup._snapshot_files(target)
        databases = backup._sqlite_files(files)
        assert len(databases) == 2
        assert all(_version(path) == "frozen" for path in databases)
        dump, = [path for path in files if path.name == "review-index.dump"]
        sql("CREATE DATABASE restored_recordbench;")
        execute(
            "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
            "-U", "recordbench", "-d", "restored_recordbench", input_bytes=dump.read_bytes(),
        )
        assert sql("SELECT version FROM synthetic_state;", "restored_recordbench") == "frozen"
        assert sql("SELECT version FROM synthetic_state;") == "live"
        assert _version(node.control) == _version(node.registry) == "live"
        execute("pg_amcheck", "-U", "recordbench", "-d", "restored_recordbench", "--install-missing")
    finally:
        subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=True)
