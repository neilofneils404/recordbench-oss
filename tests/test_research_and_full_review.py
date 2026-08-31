from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_intelligence.workflow_jobs import ReviewCoordinator, ReviewDecisionResult
from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceStore


ACTOR = "development-workflow-user"


class EvidenceEchoGenerator:
    available = True

    def generate(self, **kwargs):
        evidence = kwargs["evidence"]
        return {
            "answerable": bool(evidence),
            "claims": [
                {"text": item.excerpt[:600], "evidence_ids": [item.evidence_id]}
                for item in evidence[:1]
            ],
            "limitation": None,
            "missing_information": "",
        }


def _store(tmp_path: Path, count: int = 4):
    store = WorkspaceStore(tmp_path / "workbench.sqlite")
    principal = store.upsert_principal(
        "test", ACTOR, "Workflow Reviewer", ACTOR, preferred_principal_id=ACTOR
    )
    matter = store.create_matter("Generated workflow matter", "Public fixture", principal.principal_id)
    catalog = [
            {
                "document_id": f"{index:032x}",
                "version_id": f"{index + 10_000:032x}",
                "action_token": f"{index + 20_000:032x}",
                "display_name": f"Generated source {index:05d}.txt",
                "relative_path": f"generated/{index:05d}.txt",
                "media_type": "text/plain",
                "kind": "TXT",
                "source_state": "ready",
                "tone": "ready",
                "state_label": "Searchable",
                "count_label": "1 line",
                "processing_stage": "",
                "completed_units": 1,
                "total_units": 1,
                "page_count": 1,
                "duration_ms": 0,
                "byte_size": 40,
                "origin": "upload",
                "retryable": False,
                "removable": True,
                "has_video": False,
            }
            for index in range(1, count + 1)
        ]
    store.upsert_source_catalog(
        matter.matter_id,
        catalog,
    )
    store.reconcile_source_organizations(
        matter.matter_id,
        tuple(
            (str(item["document_id"]), "upload", str(item["relative_path"]))
            for item in catalog
        ),
    )
    return store, matter


def test_workflow_migration_matches_operator_copy():
    root = Path(__file__).parents[1]
    assert (
        root / "src/case_intelligence/migrations/sqlite/0021_research_and_full_review.sql"
    ).read_bytes() == (
        root / "migrations/sqlite/0021_research_and_full_review.sql"
    ).read_bytes()


def test_research_is_idempotent_checkpointed_recoverable_and_retryable(tmp_path):
    store, matter = _store(tmp_path)
    request_key = "research-request-" + "a" * 32
    first, created = store.queue_research_job(
        matter.matter_id, ACTOR, "What happened?", "Incident chronology", request_key
    )
    second, duplicated = store.queue_research_job(
        matter.matter_id, ACTOR, "What happened?", "Incident chronology", request_key
    )
    assert created is True and duplicated is False and first.job_id == second.job_id
    claimed = store.claim_research_job("research-worker-test")
    assert claimed is not None and claimed.job_id == first.job_id
    store.set_research_plan(first.job_id, {"queries": ["one", "two"]}, 4)
    store.update_research_progress(
        first.job_id,
        stage="searching",
        message="First pass complete.",
        completed_steps=1,
        candidate_count=12,
        evidence_count=5,
    )
    store.checkpoint_research_job(
        first.job_id,
        {"passes": [{"query": "one", "status": "supported"}], "evidence": []},
    )
    path = store.path
    store.close()

    restarted = WorkspaceStore(path)
    assert restarted.recover_running_research_jobs() == 1
    recovered = restarted.research_job(matter.matter_id, ACTOR, first.job_id)
    assert recovered.state == "queued" and recovered.completed_steps == 1
    assert recovered.result["passes"][0]["query"] == "one"
    assert restarted.claim_research_job("research-worker-two").job_id == first.job_id
    cancelling = restarted.cancel_research_job(matter.matter_id, ACTOR, first.job_id)
    assert cancelling.stage == "cancelling"
    cancelled = restarted.fail_research_job(first.job_id, "Research cancelled.")
    assert cancelled.state == "cancelled"
    retried = restarted.retry_research_job(matter.matter_id, ACTOR, first.job_id)
    assert retried.state == "queued" and retried.result == {} and retried.completed_steps == 0
    restarted.close()


def test_full_review_freezes_every_source_versions_criteria_and_computes_validation(tmp_path):
    store, matter = _store(tmp_path, count=120)
    criterion, version_one = store.create_review_criterion(
        matter.matter_id,
        ACTOR,
        title="Generated topic",
        instructions="Include a source that contains the generated topic.",
    )
    version_two = store.add_review_criterion_version(
        matter.matter_id,
        ACTOR,
        criterion.criterion_id,
        title="Generated topic",
        instructions="Include a source that expressly contains the generated topic.",
        exclude_guidance="Do not infer a match from the filename alone.",
    )
    assert version_one.version_number == 1 and version_two.version_number == 2
    current = store.review_criterion(matter.matter_id, criterion.criterion_id)
    assert current.version_count == 2 and current.current_version_id == version_two.criterion_version_id

    run = store.queue_review_run(
        matter.matter_id, ACTOR, version_two.criterion_version_id, run_kind="full"
    )
    assert run.snapshot_count == 120
    page = store.review_decisions(
        matter.matter_id, ACTOR, run.run_id, validation_only=True, page_size=100
    )
    assert page.total == 50
    assert store.claim_review_run("full-review-worker").run_id == run.run_id
    all_rows = store.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)
    for index, item in enumerate(all_rows):
        decision = "included" if index % 4 in {0, 1} else "excluded"
        store.record_review_decision(
            run.run_id, item.document_id, decision=decision, rationale="Generated decision"
        )
    finished = store.finish_review_run(run.run_id)
    assert finished.state == "succeeded" and finished.reviewed_count == 120

    sample = store.review_decisions(
        matter.matter_id, ACTOR, run.run_id, validation_only=True, page_size=100
    ).items
    # Use the saved machine labels to create TP, FP, FN, and TN exactly once.
    included = [item for item in sample if item.machine_decision == "included"][:2]
    excluded = [item for item in sample if item.machine_decision == "excluded"][:2]
    assert len(included) == 2 and len(excluded) == 2
    store.adjudicate_review_decision(
        matter.matter_id, ACTOR, run.run_id, included[0].document_id, human_decision="agree"
    )
    store.adjudicate_review_decision(
        matter.matter_id, ACTOR, run.run_id, included[1].document_id, human_decision="exclude"
    )
    store.adjudicate_review_decision(
        matter.matter_id, ACTOR, run.run_id, excluded[0].document_id, human_decision="include"
    )
    store.adjudicate_review_decision(
        matter.matter_id, ACTOR, run.run_id, excluded[1].document_id, human_decision="agree"
    )
    metrics = store.review_validation_metrics(matter.matter_id, ACTOR, run.run_id)
    assert metrics["true_positive"] == metrics["false_positive"] == 1
    assert metrics["false_negative"] == metrics["true_negative"] == 1
    assert metrics["precision"] == metrics["recall"] == pytest.approx(0.5)
    assert metrics["elusion"] == metrics["richness"] == metrics["error_rate"] == pytest.approx(0.5)
    store.close()


def test_full_review_coordinator_isolates_one_source_failure(tmp_path):
    store, matter = _store(tmp_path, count=3)
    criterion, version = store.create_review_criterion(
        matter.matter_id,
        ACTOR,
        title="Generated topic",
        instructions="Include generated topic material.",
    )
    run = store.queue_review_run(
        matter.matter_id, ACTOR, version.criterion_version_id, run_kind="full"
    )
    failed_document = f"{2:032x}"

    def process(_run, decision, _cancelled):
        if decision.document_id == failed_document:
            raise RuntimeError("generated source-level failure")
        return ReviewDecisionResult("included", "Generated supported result")

    coordinator = ReviewCoordinator(store, process=process, workers=1)
    coordinator.notify()
    deadline = time.monotonic() + 5
    finished = run
    while time.monotonic() < deadline:
        finished = store.review_run(matter.matter_id, ACTOR, run.run_id)
        if finished.state == "succeeded":
            break
        time.sleep(0.01)
    assert finished.state == "succeeded"
    assert finished.included_count == 2 and finished.attention_count == 1
    failed = store.review_decision(matter.matter_id, ACTOR, run.run_id, failed_document)
    assert failed.machine_decision == "needs_attention"
    assert "other sources continued" in failed.error_message
    coordinator.close()
    store.close()


def test_full_review_honors_a_frozen_source_set(tmp_path):
    store, matter = _store(tmp_path, count=20)
    scoped_ids = tuple(f"{index:032x}" for index in range(1, 8))
    source_set = store.create_source_set(
        matter.matter_id, "Generated seven", scoped_ids, ACTOR
    )
    _criterion, version = store.create_review_criterion(
        matter.matter_id,
        ACTOR,
        title="Scoped generated topic",
        instructions="Include generated topic material.",
    )
    run = store.queue_review_run(
        matter.matter_id,
        ACTOR,
        version.criterion_version_id,
        run_kind="full",
        source_set_id=source_set.source_set_id,
    )
    frozen = store.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)
    assert run.snapshot_count == 7
    assert {item.document_id for item in frozen} == set(scoped_ids)
    # Later changes to the saved set do not mutate an already frozen run.
    store.add_sources_to_set(
        matter.matter_id, source_set.source_set_id, (f"{8:032x}",), ACTOR
    )
    frozen_again = store.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)
    assert {item.document_id for item in frozen_again} == set(scoped_ids)
    store.close()


def test_full_review_uses_two_bounded_source_slots(tmp_path):
    store, matter = _store(tmp_path, count=8)
    _criterion, version = store.create_review_criterion(
        matter.matter_id,
        ACTOR,
        title="Bounded concurrency",
        instructions="Include generated topic material.",
    )
    run = store.queue_review_run(
        matter.matter_id, ACTOR, version.criterion_version_id, run_kind="full"
    )
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def process(_run, _decision, _cancelled):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return ReviewDecisionResult("included", "Generated supported result")

    coordinator = ReviewCoordinator(
        store, process=process, workers=1, source_concurrency=2
    )
    coordinator.notify()
    deadline = time.monotonic() + 5
    finished = run
    while time.monotonic() < deadline:
        finished = store.review_run(matter.matter_id, ACTOR, run.run_id)
        if finished.state == "succeeded":
            break
        time.sleep(0.01)
    assert finished.state == "succeeded"
    assert finished.reviewed_count == 8
    assert maximum_active == 2
    coordinator.close()
    store.close()


def test_review_workspace_runs_exports_and_final_bundle_include_new_work_product(tmp_path):
    runtime = tmp_path / "runtime"
    with TestClient(
        create_workbench_app(runtime, generator=EvidenceEchoGenerator(), auth_mode="test")
    ) as client:
        created = client.post(
            "/matters",
            data={"name": "Generated web workflow", "descriptor": "Public fixture"},
            follow_redirects=False,
        )
        slug = re.search(
            r"/matters/(m-[0-9a-f]{12})/setup", created.headers["location"]
        ).group(1)
        uploaded = client.post(
            f"/matters/{slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "generated-source.txt",
                        b"The generated source says the blue vehicle arrived at noon.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert uploaded.status_code == 200
        quick = client.get(f"/matters/{slug}")
        assert "Quick answer" in quick.text and "Deep research" in quick.text and "Full review" in quick.text

        research_page = client.get(f"/matters/{slug}/research")
        key = re.search(r'name="request_key" value="([^"]+)"', research_page.text).group(1)
        research_start = client.post(
            f"/matters/{slug}/research",
            data={
                "title": "Generated chronology",
                "question": "What does the record say about the blue vehicle?",
                "request_key": key,
                "source_set": "",
            },
            follow_redirects=False,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            research_result = client.get(research_start.headers["location"])
            if "Verified synthesis" in research_result.text:
                break
            time.sleep(0.02)
        assert "Evidence ledger" in research_result.text
        research_id = re.search(
            r"job=(research-job-[0-9a-f]{32})", research_start.headers["location"]
        ).group(1)
        research_status = client.get(
            f"/matters/{slug}/research/{research_id}/status"
        )
        assert research_status.status_code == 200
        assert not ({"summary", "evidence", "question"} & research_status.json().keys())
        research_export = re.search(
            r'href="([^"]+/research-[^/]+/export\?format=json)"', research_result.text
        )
        assert research_export and client.get(research_export.group(1)).status_code == 200

        criterion_create = client.post(
            f"/matters/{slug}/full-review/criteria",
            data={
                "title": "Vehicle references",
                "instructions": "Include sources that mention the blue vehicle.",
                "include_guidance": "An express blue vehicle reference.",
                "exclude_guidance": "No express vehicle reference.",
            },
            follow_redirects=False,
        )
        criterion_page = client.get(criterion_create.headers["location"])
        version_id = re.search(
            r'name="criterion_version_id" value="([^"]+)"', criterion_page.text
        ).group(1)
        review_start = client.post(
            f"/matters/{slug}/full-review/runs",
            data={"criterion_version_id": version_id, "run_kind": "sample", "source_set": ""},
            follow_redirects=False,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            review_result = client.get(review_start.headers["location"])
            if "Review complete:" in review_result.text:
                break
            time.sleep(0.02)
        assert "Every-source ledger" in review_result.text
        review_id = re.search(
            r"run=(review-run-[0-9a-f]{32})", review_start.headers["location"]
        ).group(1)
        review_status = client.get(f"/matters/{slug}/full-review/{review_id}/status")
        assert review_status.status_code == 200
        assert not ({"rationale", "citations", "source_name"} & review_status.json().keys())
        csv_url = re.search(r'href="([^"]+/export\?format=csv)"', review_result.text).group(1)
        csv_export = client.get(csv_url)
        assert csv_export.status_code == 200 and "Machine decision" in csv_export.text

        second = client.post(
            "/matters",
            data={"name": "Generated isolation matter", "descriptor": "Public fixture"},
            follow_redirects=False,
        )
        second_slug = re.search(
            r"/matters/(m-[0-9a-f]{12})/setup", second.headers["location"]
        ).group(1)
        assert client.get(
            f"/matters/{second_slug}/research/{research_id}/status"
        ).status_code == 404
        assert client.get(
            f"/matters/{second_slug}/research/{research_id}/export?format=json"
        ).status_code == 404
        assert client.get(
            f"/matters/{second_slug}/full-review/{review_id}/status"
        ).status_code == 404
        assert client.get(
            f"/matters/{second_slug}/full-review/{review_id}/export?format=csv"
        ).status_code == 404

        bundle = client.get(f"/matters/{slug}/export")
        assert bundle.status_code == 200
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            assert any(name.startswith("research/") and name.endswith(".json") for name in names)
            assert any(name.startswith("full-review/") and name.endswith(".csv") for name in names)
