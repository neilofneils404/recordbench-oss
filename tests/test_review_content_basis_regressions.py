from __future__ import annotations

import hashlib
import io
import sqlite3
from dataclasses import asdict

import pytest

import case_intelligence.workbench as workbench_module
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import CaseIntelligenceWorkbench
from case_intelligence.workspace_store import WorkspaceProblem


ACTOR = "development-basis-reviewer"


def _workbench(runtime_dir):
    bench = CaseIntelligenceWorkbench(
        runtime_dir,
        generator=UnavailableGenerator(),
    )
    bench.workspace.upsert_principal(
        "test",
        ACTOR,
        "Basis Reviewer",
        ACTOR,
        preferred_principal_id=ACTOR,
    )
    return bench


def _matter_with_source(bench, name: str, text: bytes):
    matter = bench.create_matter(name, "Synthetic content-basis fixture", ACTOR)
    document, _change = bench.source_store(matter).store_stream(
        "generated-record.txt",
        "text/plain",
        io.BytesIO(text),
    )
    assert document.state == "ready"
    return matter, document


def _criterion(bench, matter):
    _record, version = bench.workspace.create_review_criterion(
        matter.matter_id,
        ACTOR,
        title="Generated event criterion",
        instructions="Include the generated event record.",
    )
    return version


def test_review_snapshot_refuses_empty_content_basis_atomically(tmp_path) -> None:
    bench = _workbench(tmp_path / "runtime")
    try:
        affected, affected_document = _matter_with_source(
            bench,
            "Generated transitional matter",
            b"Generated event EVT-4821 occurred at 08:42:17.",
        )
        unaffected, _unaffected_document = _matter_with_source(
            bench,
            "Generated complete matter",
            b"Generated event EVT-9102 occurred at 09:14:03.",
        )
        affected_version = _criterion(bench, affected)
        unaffected_version = _criterion(bench, unaffected)
        with bench.workspace.connection:
            bench.workspace.connection.execute(
                "UPDATE workbench_source_catalog SET content_basis_digest='' "
                "WHERE matter_id=? AND document_id=?",
                (affected.matter_id, affected_document.document_id),
            )

        with pytest.raises(WorkspaceProblem, match="source-content tracking"):
            bench.workspace.queue_review_run(
                affected.matter_id,
                ACTOR,
                affected_version.criterion_version_id,
                run_kind="full",
            )

        assert bench.workspace.connection.execute(
            "SELECT COUNT(*) FROM workbench_review_run WHERE matter_id=?",
            (affected.matter_id,),
        ).fetchone()[0] == 0
        assert bench.workspace.connection.execute(
            "SELECT COUNT(*) FROM workbench_review_decision WHERE matter_id=?",
            (affected.matter_id,),
        ).fetchone()[0] == 0
        assert bench.workspace.connection.execute(
            "SELECT COUNT(*) FROM workbench_review_event"
        ).fetchone()[0] == 0

        unaffected_run = bench.workspace.queue_review_run(
            unaffected.matter_id,
            ACTOR,
            unaffected_version.criterion_version_id,
            run_kind="full",
        )
        assert unaffected_run.snapshot_count == 1
    finally:
        bench.close()


class _PostgresCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _PostgresConnection:
    def __init__(self) -> None:
        self.rollbacks = 0

    def cursor(self):
        return _PostgresCursor()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


def test_postgres_retention_failure_does_not_skip_legacy_basis_repair(
    tmp_path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    original = _workbench(runtime)
    matter, document = _matter_with_source(
        original,
        "Generated migrated matter",
        b"Generated machine record EVT-4821 occurred at 08:42:17.",
    )
    expected_basis = original.workspace.source_catalog_record(
        matter.matter_id, document.document_id
    ).content_basis_digest
    assert len(expected_basis) == 64
    original.close()

    database = sqlite3.connect(runtime / "workbench.sqlite")
    try:
        database.execute(
            "ALTER TABLE workbench_source_catalog DROP COLUMN content_basis_digest"
        )
        database.commit()
    finally:
        database.close()

    postgres = _PostgresConnection()
    monkeypatch.setattr(
        workbench_module,
        "apply_postgres_migrations",
        lambda _cursor: None,
    )

    def retention_unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic PostgreSQL retention outage")

    monkeypatch.setattr(
        workbench_module,
        "retain_postgres_workbench_matters",
        retention_unavailable,
    )

    reopened = CaseIntelligenceWorkbench(
        runtime,
        generator=UnavailableGenerator(),
        postgres_connection=postgres,
        learned_retrieval=True,
    )
    try:
        repaired = reopened.workspace.source_catalog_record(
            matter.matter_id, document.document_id
        )
        assert postgres.rollbacks == 1
        assert reopened.learned_retrieval is False
        assert repaired.content_basis_digest == expected_basis

        assert reopened.full_review is not None
        reopened.full_review.close()
        reopened.full_review = None
        version = _criterion(reopened, matter)
        queued = reopened.workspace.queue_review_run(
            matter.matter_id,
            ACTOR,
            version.criterion_version_id,
            run_kind="full",
        )
        claimed = reopened.workspace.claim_review_run("basis-review-worker")
        assert claimed is not None and claimed.run_id == queued.run_id
        decision = reopened.workspace.next_review_decision(queued.run_id)
        assert decision is not None
        assert decision.source_basis_digest == expected_basis

        source_store = reopened.source_store(matter)
        current = source_store.get(document.document_id)
        current_version = current.version_id
        edited = "Generated machine record EVT-4821 now states 09:03:11."
        unit = asdict(current.parsed_units()[0])
        current.units = [
            {
                **unit,
                "text": edited,
                "excerpt_digest": hashlib.sha256(edited.encode("utf-8")).hexdigest(),
            }
        ]
        source_store._save((current.document_id,))
        assert current.version_id == current_version

        result = reopened._process_review_decision(claimed, decision, lambda: False)
        assert result.decision == "needs_attention"
        assert result.citations == ()
        assert "source changed" in result.rationale.casefold()
    finally:
        reopened.close()
