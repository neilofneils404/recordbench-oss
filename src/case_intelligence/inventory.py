from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .contracts import ContentOperation, validate_relative_path
from .isolation import MatterStateRegistry
from .scanner import ScannedFile, SyntheticScanner
from .sqlite_store import SQLiteStore


class InventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanSnapshot:
    scan_run_id: str
    matter_id: str
    source_location_id: str
    idempotency_key: str
    catalog_revision: int
    binding_revision: int
    files: tuple[ScannedFile, ...]


@dataclass(frozen=True)
class InventoryOutcome:
    scan_run_id: str
    state: str
    new: int = 0
    unchanged: int = 0
    changed: int = 0
    missing: int = 0
    reappeared: int = 0


def _utc(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("clock must return UTC")
    return value.isoformat().replace("+00:00", "Z")


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


class InventoryService:
    def __init__(
        self,
        store: SQLiteStore,
        registry: MatterStateRegistry,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        _test_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.clock = clock
        self._test_hook = _test_hook

    def register_location(
        self,
        matter_id: str,
        source_location_id: str,
        display_name: str,
        synthetic_root: Path,
        synthetic_unc_root: str,
        *,
        binding_revision: int = 1,
        mapping_revision: int = 1,
    ) -> None:
        root = Path(synthetic_root).resolve(strict=True)
        if root == Path("/mnt") or Path("/mnt") in root.parents:
            raise ValueError("/mnt roots are prohibited")
        if not synthetic_unc_root.startswith("\\\\synthetic\\"):
            raise ValueError("only synthetic UNC placeholders are accepted")

        def write() -> None:
            with self.store.transaction(immediate=True) as db:
                owner = db.execute(
                    "SELECT matter_id FROM matter_catalog WHERE matter_id=?", (matter_id,)
                ).fetchone()
                if owner is None:
                    raise ValueError("matter must be registered first")
                db.execute(
                    "INSERT INTO source_location(source_location_id,matter_id,display_name,enabled,catalog_revision) VALUES(?,?,?,?,0)",
                    (source_location_id, matter_id, display_name, 1),
                )
                db.execute(
                    "INSERT INTO scanner_binding VALUES(?,?,?,?)",
                    (source_location_id, matter_id, str(root), binding_revision),
                )
                db.execute(
                    "INSERT INTO windows_mapping VALUES(?,?,?,?)",
                    (source_location_id, matter_id, synthetic_unc_root, mapping_revision),
                )
        self.registry.perform_active(matter_id, ContentOperation.INGEST, write)

    def prepare_snapshot(self, matter_id: str, source_location_id: str, idempotency_key: str) -> ScanSnapshot:
        if not idempotency_key.strip():
            raise ValueError("scan idempotency key required")

        def claim() -> tuple[str, int, int, str]:
            with self.store.transaction(immediate=True) as db:
                location = db.execute(
                    "SELECT l.catalog_revision,l.enabled,b.binding_revision,b.synthetic_root "
                    "FROM source_location l JOIN scanner_binding b USING(source_location_id) "
                    "WHERE l.matter_id=? AND l.source_location_id=?",
                    (matter_id, source_location_id),
                ).fetchone()
                if location is None or not location["enabled"]:
                    raise InventoryError("source location unavailable")
                scan_id = _id("scan", source_location_id, idempotency_key)
                existing = db.execute(
                    "SELECT state,captured_catalog_revision,binding_revision FROM scan_run WHERE scan_run_id=?",
                    (scan_id,),
                ).fetchone()
                if existing:
                    raise InventoryError(f"scan already {existing['state']}")
                now = _utc(self.clock)
                db.execute(
                    "INSERT INTO scan_run VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (scan_id, matter_id, source_location_id, idempotency_key,
                     location["catalog_revision"], location["binding_revision"],
                     "running", None, now, None),
                )
                db.execute(
                    "INSERT INTO scan_attempt VALUES(?,?,?,?,?,?,?)",
                    (f"attempt-{scan_id}-1", scan_id, 1, "running", None, now, None),
                )
                return scan_id, location["catalog_revision"], location["binding_revision"], location["synthetic_root"]
        scan_id, catalog_revision, binding_revision, root = self.registry.perform_active(
            matter_id, ContentOperation.INGEST, claim
        )
        try:
            files = SyntheticScanner(Path(root)).scan()
        except BaseException:
            self._finish_failed(scan_id, "scan_failed")
            raise
        return ScanSnapshot(scan_id, matter_id, source_location_id, idempotency_key,
                            catalog_revision, binding_revision, files)

    def inventory(self, matter_id: str, source_location_id: str, idempotency_key: str) -> InventoryOutcome:
        return self.apply_snapshot(self.prepare_snapshot(matter_id, source_location_id, idempotency_key))

    def apply_snapshot(self, snapshot: ScanSnapshot) -> InventoryOutcome:
        counts = {key: 0 for key in ("new", "unchanged", "changed", "missing", "reappeared")}

        def apply() -> InventoryOutcome:
            try:
                with self.store.transaction(immediate=True) as db:
                    scan_run = db.execute(
                        "SELECT matter_id,source_location_id,scan_idempotency_key,"
                        "captured_catalog_revision,binding_revision,state "
                        "FROM scan_run WHERE scan_run_id=?",
                        (snapshot.scan_run_id,),
                    ).fetchone()
                    if scan_run is None or scan_run["state"] != "running" or any((
                        scan_run["matter_id"] != snapshot.matter_id,
                        scan_run["source_location_id"] != snapshot.source_location_id,
                        scan_run["scan_idempotency_key"] != snapshot.idempotency_key,
                        scan_run["captured_catalog_revision"] != snapshot.catalog_revision,
                        scan_run["binding_revision"] != snapshot.binding_revision,
                    )):
                        raise InventoryError("snapshot does not match its running scan")
                    location = db.execute(
                        "SELECT l.catalog_revision,l.enabled,b.binding_revision FROM source_location l "
                        "JOIN scanner_binding b USING(source_location_id) WHERE l.matter_id=? AND l.source_location_id=?",
                        (snapshot.matter_id, snapshot.source_location_id),
                    ).fetchone()
                    if (location is None or not location["enabled"] or
                        location["binding_revision"] != snapshot.binding_revision or
                        location["catalog_revision"] != snapshot.catalog_revision):
                        raise _Superseded
                    now = _utc(self.clock)
                    seen: set[str] = set()
                    for observed in snapshot.files:
                        validate_relative_path(observed.relative_path)
                        seen.add(observed.relative_path)
                        row = db.execute(
                            "SELECT * FROM source_file WHERE matter_id=? AND source_location_id=? AND relative_path=?",
                            (snapshot.matter_id, snapshot.source_location_id, observed.relative_path),
                        ).fetchone()
                        if row is None:
                            source_file_id = _id("file", snapshot.matter_id, snapshot.source_location_id, observed.relative_path)
                            current_file_id = source_file_id
                            version_id = _id("version", source_file_id, observed.sha256)
                            db.execute(
                                "INSERT INTO source_file VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (source_file_id, snapshot.matter_id, snapshot.source_location_id,
                                 observed.relative_path, observed.display_name, observed.media_type,
                                 "available", now, now, version_id),
                            )
                            self._insert_version(db, source_file_id, version_id, snapshot, observed, now)
                            self._queue_job(db, snapshot.matter_id, version_id, observed.media_type, now)
                            counts["new"] += 1
                        else:
                            current_file_id = row["source_file_id"]
                            version = db.execute(
                                "SELECT source_version_id FROM source_version WHERE source_file_id=? AND sha256=?",
                                (row["source_file_id"], observed.sha256),
                            ).fetchone()
                            was_missing = row["availability"] == "missing"
                            if version:
                                version_id = version["source_version_id"]
                                counts["reappeared" if was_missing else "unchanged"] += 1
                            else:
                                version_id = _id("version", row["source_file_id"], observed.sha256)
                                self._insert_version(db, row["source_file_id"], version_id, snapshot, observed, now)
                                self._queue_job(db, snapshot.matter_id, version_id, observed.media_type, now)
                                counts["changed"] += 1
                            db.execute(
                                "UPDATE source_file SET availability='available',last_seen_at=?,display_name=?,media_type=?,current_source_version_id=? WHERE source_file_id=?",
                                (now, observed.display_name, observed.media_type, version_id, row["source_file_id"]),
                            )
                        db.execute(
                            "INSERT INTO scan_observation VALUES(?,?,?,?)",
                            (snapshot.scan_run_id, snapshot.matter_id, current_file_id, version_id),
                        )
                        if self._test_hook:
                            self._test_hook("after_observation")
                    prior = db.execute(
                        "SELECT source_file_id,relative_path,availability FROM source_file WHERE matter_id=? AND source_location_id=?",
                        (snapshot.matter_id, snapshot.source_location_id),
                    ).fetchall()
                    for row in prior:
                        if row["relative_path"] not in seen and row["availability"] != "missing":
                            db.execute("UPDATE source_file SET availability='missing' WHERE source_file_id=?", (row["source_file_id"],))
                            counts["missing"] += 1
                    if self._test_hook:
                        self._test_hook("after_missing")
                    updated = db.execute(
                        "UPDATE source_location SET catalog_revision=catalog_revision+1 WHERE source_location_id=? AND catalog_revision=?",
                        (snapshot.source_location_id, snapshot.catalog_revision),
                    )
                    if updated.rowcount != 1:
                        raise _Superseded
                    if self._test_hook:
                        self._test_hook("after_cas")
                    db.execute(
                        "UPDATE scan_run SET state='succeeded',completed_at=? WHERE scan_run_id=? AND state='running'",
                        (now, snapshot.scan_run_id),
                    )
                    db.execute(
                        "UPDATE scan_attempt SET state='succeeded',completed_at=? "
                        "WHERE scan_run_id=? AND state='running'",
                        (now, snapshot.scan_run_id),
                    )
                return InventoryOutcome(snapshot.scan_run_id, "succeeded", **counts)
            except _Superseded:
                self._finish_failed(snapshot.scan_run_id, "catalog_revision_conflict", superseded=True)
                return InventoryOutcome(snapshot.scan_run_id, "superseded")
            except BaseException:
                self._finish_failed(snapshot.scan_run_id, "apply_failed")
                raise
        try:
            return self.registry.perform_active(snapshot.matter_id, ContentOperation.INGEST, apply)
        except BaseException:
            # If the active fence rejects before ``apply`` starts, no SQLite
            # lock is held. Preserve the path-free failed attempt durably.
            self._finish_failed(snapshot.scan_run_id, "matter_fence_rejected")
            raise

    def _insert_version(self, db: sqlite3.Connection, source_file_id: str, version_id: str,
                        snapshot: ScanSnapshot, item: ScannedFile, now: str) -> None:
        db.execute(
            "INSERT INTO source_version VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (version_id, source_file_id, snapshot.matter_id, snapshot.source_location_id,
             item.relative_path, item.display_name, item.media_type, item.byte_size,
             item.sha256, item.stable_device, item.stable_inode, item.stable_mtime_ns, now),
        )

    def _queue_job(self, db: sqlite3.Connection, matter_id: str, version_id: str, media_type: str, now: str) -> None:
        state = "queued" if media_type == "text/plain" else "not_processed"
        job_id = _id("job", "derive_text", version_id, "plain-text-v1")
        db.execute(
            "INSERT OR IGNORE INTO job VALUES(?,?,?,?,?,?,?,?)",
            (job_id, matter_id, "derive_text", version_id, "plain-text-v1", state, now, now),
        )

    def _finish_failed(self, scan_id: str, category: str, *, superseded: bool = False) -> None:
        with self.store.transaction(immediate=True) as db:
            db.execute(
                "UPDATE scan_run SET state=?,failure_category=?,completed_at=? WHERE scan_run_id=? AND state='running'",
                ("superseded" if superseded else "failed", category, _utc(self.clock), scan_id),
            )
            db.execute(
                "UPDATE scan_attempt SET state=?,failure_category=?,completed_at=? "
                "WHERE scan_run_id=? AND state='running'",
                ("superseded" if superseded else "failed", category, _utc(self.clock), scan_id),
            )


class _Superseded(Exception):
    pass
