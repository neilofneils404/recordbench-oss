from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_intelligence.answer_jobs import AnswerCoordinator, AnswerJobFailure, AnswerResult
from case_intelligence.workbench import (
    CaseIntelligenceWorkbench,
    WorkbenchCitation,
    create_workbench_app,
)
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore


ACTOR = "development-answer-user"
WEB_ACTOR = "development-taylor-morgan"


def _seed_principal(store: WorkspaceStore, actor: str) -> None:
    store.upsert_principal(
        "test",
        actor,
        actor.replace("-", " ").title(),
        actor,
        preferred_principal_id=actor,
    )


def _workspace(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    _seed_principal(store, ACTOR)
    matter = store.create_matter("Durable answer matter", "Synthetic", ACTOR)
    conversation = store.get_conversation(matter.matter_id)
    return store, matter, conversation


def _queue(store, matter, conversation, suffix="1", question="What is supported?"):
    return store.queue_answer_job(
        matter.matter_id,
        conversation.conversation_id,
        matter.owner_id,
        question,
        f"answer-request-{suffix * 32}",
    )


def _wait_for(store, matter, job_id, states, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get_answer_job(matter.matter_id, matter.owner_id, job_id)
        if job.state in states:
            return job
        time.sleep(0.01)
    return store.get_answer_job(matter.matter_id, matter.owner_id, job_id)


def test_answer_migration_matches_operator_copy():
    root = Path(__file__).parents[1]
    assert (
        root / "src/case_intelligence/migrations/sqlite/0004_durable_answer_jobs.sql"
    ).read_bytes() == (
        root / "migrations/sqlite/0004_durable_answer_jobs.sql"
    ).read_bytes()


def test_answer_evidence_anchors_diversify_sources_before_backfill():
    citations = tuple(
        WorkbenchCitation(
            source_name=f"Generated source {document}.pdf",
            location="Page 1",
            excerpt=f"Generated passage {ordinal}",
            href=f"/generated/{ordinal}",
            support_token=f"{ordinal:040x}",
            matter_id="generated-matter",
            document_id=document,
            source_version_id="generated-v1",
            excerpt_digest=f"{ordinal + 100:064x}",
            chunk_id=f"chunk-{ordinal}",
            unit_number=1,
            line_start=None,
            line_end=None,
            evidence_kind="document",
        )
        for ordinal, document in enumerate(
            ("alpha", "alpha", "alpha", "alpha", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"),
            1,
        )
    )
    selected = CaseIntelligenceWorkbench._answer_evidence_citations(
        object(), None, citations, maximum=8
    )
    assert [item.document_id for item in selected].count("alpha") == 2
    assert len({item.document_id for item in selected}) == 7


def test_queue_is_atomic_idempotent_and_actor_matter_scoped(tmp_path):
    store, matter, conversation = _workspace(tmp_path)

    def submit():
        return _queue(store, matter, conversation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _value: submit(), range(2)))
    assert {job.job_id for job, _created in results} == {results[0][0].job_id}
    assert sorted(created for _job, created in results) == [False, True]
    messages = store.messages(matter.matter_id, conversation.conversation_id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "What is supported?")
    ]
    with pytest.raises(WorkspaceProblem, match="different question"):
        store.queue_answer_job(
            matter.matter_id,
            conversation.conversation_id,
            ACTOR,
            "A different question",
            "answer-request-" + "1" * 32,
        )
    with pytest.raises(KeyError):
        store.get_answer_job(matter.matter_id, "another-actor", results[0][0].job_id)

    _seed_principal(store, "another-actor")
    foreign = store.create_matter("Foreign matter", "", "another-actor")
    with pytest.raises(KeyError):
        store.get_answer_job(foreign.matter_id, "another-actor", results[0][0].job_id)
    store.close()


def test_completion_is_exactly_once_and_events_are_append_only(tmp_path):
    store, matter, conversation = _workspace(tmp_path)
    queued, _ = _queue(store, matter, conversation)
    claimed = store.claim_answer_job("answer-worker-one")
    assert claimed is not None and claimed.job_id == queued.job_id
    assert store.update_answer_job_stage(
        queued.job_id, "retrieving", "Finding candidate evidence."
    )
    assert store.update_answer_job_stage(
        queued.job_id, "reranking", "Ordering evidence."
    )
    assert store.update_answer_job_stage(
        queued.job_id, "generating", "Drafting from support."
    )
    assert store.update_answer_job_stage(
        queued.job_id, "verifying", "Verifying claims."
    )
    first = store.finish_answer_job(
        queued.job_id,
        content="The searchable sources do not support an answer.",
        payload={"kind": "not-supported", "missing_information": "No support."},
    )
    second = store.finish_answer_job(
        queued.job_id,
        content="This duplicate must not be written.",
        payload={"kind": "error"},
    )
    assert first is not None and second is not None
    assert first.message_id == second.message_id
    assert len(store.messages(matter.matter_id, conversation.conversation_id)) == 2
    job = store.get_answer_job(matter.matter_id, ACTOR, queued.job_id)
    assert job.state == "succeeded" and job.result_message_id == first.message_id
    events = store.answer_events(matter.matter_id, ACTOR, queued.job_id)
    assert [event.ordinal for event in events] == list(range(1, len(events) + 1))
    assert [event.stage for event in events] == [
        "queued",
        "queued",
        "retrieving",
        "reranking",
        "generating",
        "verifying",
        "complete",
    ]
    store.close()


def test_recovery_cancel_and_retry_reuse_the_saved_question(tmp_path):
    path = tmp_path / "workspace.sqlite"
    store, matter, conversation = _workspace(tmp_path)
    queued, _ = _queue(store, matter, conversation)
    assert store.claim_answer_job("answer-worker-one").job_id == queued.job_id
    store.close()

    restarted = WorkspaceStore(path)
    assert restarted.recover_running_answer_jobs() == 1
    recovered = restarted.get_answer_job(matter.matter_id, ACTOR, queued.job_id)
    assert recovered.state == "queued" and recovered.attempts == 1
    cancelled = restarted.cancel_answer_job(matter.matter_id, ACTOR, queued.job_id)
    assert cancelled.state == "cancelled"
    retried = restarted.retry_answer_job(matter.matter_id, ACTOR, queued.job_id)
    assert retried.state == "queued" and retried.question_message_id == queued.question_message_id
    assert len(restarted.messages(matter.matter_id, conversation.conversation_id)) == 1

    claimed = restarted.claim_answer_job("answer-worker-two")
    assert claimed is not None and claimed.attempts == 2
    cancelling = restarted.cancel_answer_job(matter.matter_id, ACTOR, queued.job_id)
    assert cancelling.state == "running" and cancelling.stage == "cancelling"
    assert not restarted.update_answer_job_stage(
        queued.job_id, "generating", "This must not advance."
    )
    assert restarted.finish_answer_job(
        queued.job_id,
        content="This cancelled answer must not be written.",
        payload={"kind": "error"},
    ) is None
    assert restarted.get_answer_job(matter.matter_id, ACTOR, queued.job_id).state == "cancelled"
    assert len(restarted.messages(matter.matter_id, conversation.conversation_id)) == 1
    restarted.close()


def test_claim_rotates_across_actor_matter_lanes(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    _seed_principal(store, ACTOR)
    alpha = store.create_matter("Alpha", "", ACTOR)
    alpha_one = store.get_conversation(alpha.matter_id)
    alpha_two = store.create_conversation(alpha.matter_id)
    bravo = store.create_matter("Bravo", "", ACTOR)
    bravo_one = store.get_conversation(bravo.matter_id)
    alpha_job_one, _ = _queue(store, alpha, alpha_one, "1")
    alpha_job_two, _ = _queue(store, alpha, alpha_two, "2")
    bravo_job, _ = _queue(store, bravo, bravo_one, "3")
    assert store.answer_queue_position(alpha.matter_id, ACTOR, alpha_job_one.job_id) == 1

    first = store.claim_answer_job("answer-worker-one")
    second = store.claim_answer_job("answer-worker-two")
    third = store.claim_answer_job("answer-worker-three")
    assert first is not None and first.job_id == alpha_job_one.job_id
    assert second is not None and second.job_id == bravo_job.job_id
    assert third is not None and third.job_id == alpha_job_two.job_id
    store.close()


def test_coordinator_reports_real_stages_and_cancellation(tmp_path):
    store, matter, conversation = _workspace(tmp_path)
    queued, _ = _queue(store, matter, conversation)

    def process(_job, stage, _cancelled):
        for stage_key in ("retrieving", "reranking", "generating", "verifying"):
            stage(stage_key, f"stage {stage_key}")
        return AnswerResult("Supported answer", {"kind": "generated"})

    coordinator = AnswerCoordinator(store, process=process, workers=1)
    coordinator.notify()
    finished = _wait_for(store, matter, queued.job_id, {"succeeded"})
    assert finished.state == "succeeded"
    assert [
        event.stage
        for event in store.answer_events(matter.matter_id, ACTOR, queued.job_id)
        if event.stage in {"retrieving", "reranking", "generating", "verifying"}
    ] == ["retrieving", "reranking", "generating", "verifying"]
    coordinator.close()
    store.close()

    store, matter, conversation = _workspace(tmp_path / "cancel")
    queued, _ = _queue(store, matter, conversation)
    started = threading.Event()
    release = threading.Event()

    def blocking(_job, stage, _cancelled):
        stage("retrieving", "Finding evidence")
        started.set()
        release.wait(timeout=2)
        stage("generating", "Drafting")
        return AnswerResult("Must not persist", {"kind": "generated"})

    coordinator = AnswerCoordinator(store, process=blocking, workers=1)
    coordinator.notify()
    assert started.wait(timeout=2)
    store.cancel_answer_job(matter.matter_id, ACTOR, queued.job_id)
    release.set()
    cancelled = _wait_for(store, matter, queued.job_id, {"cancelled"})
    assert cancelled.state == "cancelled"
    assert len(store.messages(matter.matter_id, conversation.conversation_id)) == 1
    coordinator.close()
    store.close()


def test_coordinator_persists_staff_safe_failure_and_retry(tmp_path):
    store, matter, conversation = _workspace(tmp_path)
    queued, _ = _queue(store, matter, conversation)
    attempts = 0

    def process(_job, stage, _cancelled):
        nonlocal attempts
        attempts += 1
        stage("retrieving", "Finding evidence")
        if attempts == 1:
            raise AnswerJobFailure("Answering is temporarily unavailable.")
        stage("reranking", "Ordering evidence")
        stage("generating", "Drafting")
        stage("verifying", "Verifying")
        return AnswerResult("Supported on retry", {"kind": "generated"})

    coordinator = AnswerCoordinator(store, process=process, workers=1)
    coordinator.notify()
    failed = _wait_for(store, matter, queued.job_id, {"failed"})
    assert failed.message == "Answering is temporarily unavailable."
    store.retry_answer_job(matter.matter_id, ACTOR, queued.job_id)
    coordinator.notify()
    succeeded = _wait_for(store, matter, queued.job_id, {"succeeded"})
    assert succeeded.attempts == 2
    assert len(store.messages(matter.matter_id, conversation.conversation_id)) == 2
    coordinator.close()
    store.close()


def test_http_acknowledges_immediately_reconnects_cancels_retries_and_deduplicates(
    tmp_path,
):
    class BlockingEvidenceGenerator:
        available = True

        def __init__(self):
            self.calls = 0
            self.started = threading.Event()
            self.release = threading.Event()

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                self.started.set()
                self.release.wait(timeout=3)
            evidence = kwargs["evidence"][0]
            return {
                "answerable": True,
                "claims": [
                    {"text": evidence.excerpt, "evidence_ids": [evidence.evidence_id]}
                ],
                "limitation": None,
                "missing_information": "",
            }

    generator = BlockingEvidenceGenerator()
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=generator,
        answer_workers=1,
        auth_mode="test",
    )
    with TestClient(app) as client:
        created = client.post(
            "/matters",
            data={"name": "HTTP answer matter", "descriptor": "Synthetic"},
            follow_redirects=False,
        )
        slug = created.headers["location"].split("/")[2]
        client.post(
            f"/matters/{slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "record.txt",
                        b"The synthetic cobalt notebook was logged at 8:14 p.m.\n",
                        "text/plain",
                    ),
                )
            ],
        )
        bench = client.app.state.workbench
        matter = bench.matter(slug, WEB_ACTOR)
        conversation = bench.workspace.get_conversation(matter.matter_id)
        failed_id = "f" * 32
        bench.workspace.upsert_source_catalog(
            matter.matter_id,
            (
                {
                    "document_id": failed_id,
                    "version_id": "e" * 32,
                    "action_token": "d" * 32,
                    "display_name": "generated-failed-source.txt",
                    "relative_path": "generated/generated-failed-source.txt",
                    "media_type": "text/plain",
                    "kind": "TXT",
                    "source_state": "queued",
                    "tone": "processing",
                    "state_label": "Processing",
                    "count_label": "1 line",
                    "processing_stage": "Queued",
                    "completed_units": 0,
                    "total_units": 1,
                    "page_count": 0,
                    "duration_ms": 0,
                    "byte_size": 40,
                    "origin": "upload",
                    "retryable": True,
                    "removable": False,
                    "has_video": False,
                },
            ),
        )
        failed_ingest = bench.workspace.queue_upload(matter.matter_id, failed_id)
        claimed_ingest = bench.workspace.claim_ingest_job("generated-failure-worker")
        assert claimed_ingest is not None and claimed_ingest.job_id == failed_ingest.job_id
        bench.workspace.finish_ingest_job(
            failed_ingest.job_id,
            succeeded=False,
            message="Generated extraction failure",
        )
        partial = bench.workspace.matter_readiness(matter.matter_id)
        assert partial.can_query and partial.partial_query
        request_data = {
            "conversation": conversation.conversation_id,
            "question": "When was the cobalt notebook logged?",
            "request_key": "answer-request-" + "d" * 32,
        }
        started_at = time.monotonic()
        acknowledged = client.post(
            f"/matters/{slug}/ask",
            data=request_data,
            headers={"Accept": "application/json"},
        )
        acknowledgement_seconds = time.monotonic() - started_at
        assert acknowledged.status_code == 202
        assert acknowledgement_seconds < 0.75
        job = acknowledged.json()
        assert generator.started.wait(timeout=2)

        reconnected = client.get(
            f"/matters/{slug}",
            params={"conversation": conversation.conversation_id},
        )
        assert request_data["question"] in reconnected.text
        assert "This request is saved" in reconnected.text
        assert job["status_url"] in reconnected.text

        duplicate = client.post(
            f"/matters/{slug}/ask",
            data=request_data,
            headers={"Accept": "application/json"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["job_id"] == job["job_id"]
        assert len(bench.workspace.messages(matter.matter_id, conversation.conversation_id)) == 1

        foreign = client.post(
            "/matters",
            data={"name": "Foreign HTTP matter", "descriptor": "Synthetic"},
            follow_redirects=False,
        )
        foreign_slug = foreign.headers["location"].split("/")[2]
        assert client.get(
            job["status_url"].replace(f"/matters/{slug}/", f"/matters/{foreign_slug}/")
        ).status_code == 404

        cancelling = client.post(
            job["cancel_url"], headers={"Accept": "application/json"}
        )
        assert cancelling.status_code == 200
        assert cancelling.json()["stage"] == "cancelling"
        generator.release.set()
        cancelled = _wait_for(
            bench.workspace, matter, job["job_id"], {"cancelled"}
        )
        assert cancelled.state == "cancelled"
        assert len(bench.workspace.messages(matter.matter_id, conversation.conversation_id)) == 1

        retried = client.post(
            job["retry_url"], headers={"Accept": "application/json"}
        )
        assert retried.status_code == 200 and retried.json()["state"] in {
            "queued",
            "running",
            "succeeded",
        }
        succeeded = _wait_for(
            bench.workspace, matter, job["job_id"], {"succeeded"}
        )
        assert succeeded.state == "succeeded" and succeeded.attempts == 2
        completed_status = client.get(job["status_url"]).json()
        assert completed_status["result_url"].endswith(
            f"/answer-jobs/{job['job_id']}/result"
        )
        fresh_result = client.get(
            completed_status["result_url"], follow_redirects=False
        )
        assert fresh_result.status_code == 303
        assert fresh_result.headers["location"] == completed_status["workspace_url"]
        rendered_result = client.get(completed_status["result_url"])
        assert rendered_result.status_code == 200
        assert "The synthetic cobalt notebook was logged" in rendered_result.text
        assert "Source coverage when this answer was created" in rendered_result.text
        assert "1 source needs attention and is excluded" in rendered_result.text
        assert client.get(
            completed_status["result_url"].replace(
                f"/matters/{slug}/", f"/matters/{foreign_slug}/"
            ),
            follow_redirects=False,
        ).status_code == 404
        messages = bench.workspace.messages(matter.matter_id, conversation.conversation_id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[-1].payload["source_coverage"]["mode"] == "partial"
        assert messages[-1].payload["source_coverage"]["searchable_count"] == 1
        assert messages[-1].payload["source_coverage"]["total_count"] == 2
        assert messages[-1].payload["review_scope"] == {
            "mode": "focused",
            "collection_wide_request": False,
            "searchable_source_count": 1,
            "candidate_passage_count": 1,
            "candidate_source_count": 1,
            "cited_passage_count": 1,
            "cited_source_count": 1,
            "notice": (
                "RecordBench searched the index for 1 searchable source, "
                "reranked the strongest passages, and grounded this answer in "
                "1 cited source."
            ),
        }
        assistant = client.get(
            f"/matters/{slug}/assistant",
            params={"conversation": conversation.conversation_id},
        )
        assert assistant.status_code == 200
        assert "Source coverage when created" in assistant.text
        assert "Focused answer" in assistant.text
        assert "1 cited source · 1 searchable indexed" in assistant.text

        after_completion = client.post(
            f"/matters/{slug}/ask",
            data=request_data,
            headers={"Accept": "application/json"},
        )
        assert after_completion.status_code == 200
        assert after_completion.json()["job_id"] == job["job_id"]
        assert len(bench.workspace.messages(matter.matter_id, conversation.conversation_id)) == 2

        broad = client.post(
            f"/matters/{slug}/ask",
            data={
                "conversation": conversation.conversation_id,
                "question": "List every document that mentions the cobalt notebook.",
                "request_key": "answer-request-" + "e" * 32,
            },
            headers={"Accept": "application/json"},
        )
        assert broad.status_code == 202
        broad_job = _wait_for(
            bench.workspace, matter, broad.json()["job_id"], {"succeeded"}
        )
        assert broad_job.state == "succeeded"
        broad_answer = bench.workspace.messages(
            matter.matter_id, conversation.conversation_id
        )[-1]
        assert broad_answer.payload["review_scope"]["collection_wide_request"] is True
        assert "not a document-by-document completeness review" in broad_answer.payload[
            "review_scope"
        ]["notice"]
        rendered_broad = client.get(
            f"/matters/{slug}",
            params={"conversation": conversation.conversation_id},
        )
        assert "Completeness caution" in rendered_broad.text


def test_eight_session_control_plane_keeps_search_and_ingestion_responsive(tmp_path):
    class MeasuredGenerator:
        available = True

        def __init__(self):
            self.release = threading.Event()
            self.two_started = threading.Event()
            self.lock = threading.Lock()
            self.active = 0
            self.maximum_active = 0
            self.order = []

        def generate(self, **kwargs):
            evidence = kwargs["evidence"][0]
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.order.append(evidence.source_name)
                if self.active == 2:
                    self.two_started.set()
            self.release.wait(timeout=4)
            time.sleep(0.03)
            with self.lock:
                self.active -= 1
            return {
                "answerable": True,
                "claims": [
                    {"text": evidence.excerpt, "evidence_ids": [evidence.evidence_id]}
                ],
                "limitation": None,
                "missing_information": "",
            }

    generator = MeasuredGenerator()
    app = create_workbench_app(
        tmp_path / "runtime",
        generator=generator,
        background_ingestion=True,
        ingestion_workers=2,
        answer_workers=2,
        auth_mode="test",
    )
    with TestClient(app) as client:
        sessions = []
        for matter_number in range(4):
            response = client.post(
                "/matters",
                data={
                    "name": f"Concurrent matter {matter_number}",
                    "descriptor": "Synthetic concurrency acceptance",
                },
                follow_redirects=False,
            )
            slug = response.headers["location"].split("/")[2]
            client.post(
                f"/matters/{slug}/uploads",
                files=[
                    (
                        "files",
                        (
                            f"matter-{matter_number}.txt",
                            f"Matter {matter_number} records the synthetic cobalt notebook.\n".encode(),
                            "text/plain",
                        ),
                    )
                ],
            )
            matter = client.app.state.workbench.matter(slug, WEB_ACTOR)
            store = client.app.state.workbench.source_store(matter)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not all(
                document.state == "ready" for document in store.documents.values()
            ):
                time.sleep(0.01)
            assert all(document.state == "ready" for document in store.documents.values())
            first = client.app.state.workbench.workspace.get_conversation(matter.matter_id)
            second = client.app.state.workbench.workspace.create_conversation(matter.matter_id)
            sessions.append((slug, matter, first))
            sessions.append((slug, matter, second))

        jobs = []
        acknowledgement_times = []
        acceptance_started = time.monotonic()
        ordered_sessions = sessions[::2] + sessions[1::2]
        for ordinal, (slug, _matter, conversation) in enumerate(ordered_sessions):
            began = time.monotonic()
            response = client.post(
                f"/matters/{slug}/ask",
                data={
                    "conversation": conversation.conversation_id,
                    "question": "What does this matter record about the cobalt notebook?",
                    "request_key": f"answer-request-{ordinal:032x}",
                },
                headers={"Accept": "application/json"},
            )
            acknowledgement_times.append(time.monotonic() - began)
            assert response.status_code == 202
            jobs.append(response.json())
        assert generator.two_started.wait(timeout=2)
        assert max(acknowledgement_times) < 0.75

        active_slug, active_matter, _conversation = sessions[0]
        uploaded = client.post(
            f"/matters/{active_slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "new-production.txt",
                        b"A new synthetic production arrived while answers were queued.\n",
                        "text/plain",
                    ),
                )
            ],
        )
        assert uploaded.status_code == 200
        active_store = client.app.state.workbench.source_store(active_matter)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not any(
            document.display_name == "new-production.txt" and document.state == "ready"
            for document in active_store.documents.values()
        ):
            time.sleep(0.01)
        assert any(
            document.display_name == "new-production.txt" and document.state == "ready"
            for document in active_store.documents.values()
        )

        def search(session):
            slug, _matter, _conversation = session
            began = time.monotonic()
            response = client.get(
                f"/matters/{slug}",
                params={"mode": "search", "q": "cobalt notebook"},
            )
            return response.status_code, time.monotonic() - began, response.text

        with ThreadPoolExecutor(max_workers=4) as pool:
            search_results = tuple(pool.map(search, sessions[::2]))
        assert all(status == 200 and "Search this matter" in text for status, _elapsed, text in search_results)
        assert max(elapsed for _status, elapsed, _text in search_results) < 1.5

        generator.release.set()
        deadline = time.monotonic() + 8
        remaining = {job["job_id"] for job in jobs}
        while time.monotonic() < deadline and remaining:
            for job in jobs:
                if job["job_id"] not in remaining:
                    continue
                status = client.get(job["status_url"]).json()
                if status["state"] == "succeeded":
                    remaining.remove(job["job_id"])
            time.sleep(0.01)
        assert not remaining
        assert generator.maximum_active == 2
        assert len(set(generator.order[:4])) == 4
        assert client.get("/health").json()["answer_jobs"]["succeeded"] == 8
        for _slug, matter, conversation in sessions:
            messages = client.app.state.workbench.workspace.messages(
                matter.matter_id, conversation.conversation_id
            )
            assert [message.role for message in messages] == ["user", "assistant"]
        print(
            "answer_queue_control_plane_acceptance="
            + json.dumps(
                {
                    "sessions": 8,
                    "answer_workers": 2,
                    "max_active_generation": generator.maximum_active,
                    "max_acknowledgement_ms": round(
                        max(acknowledgement_times) * 1000, 1
                    ),
                    "max_concurrent_search_ms": round(
                        max(elapsed for _status, elapsed, _text in search_results) * 1000,
                        1,
                    ),
                    "all_answers_completed_ms": round(
                        (time.monotonic() - acceptance_started) * 1000, 1
                    ),
                    "first_four_lanes_distinct": len(set(generator.order[:4])) == 4,
                    "background_ingestion_completed": True,
                },
                sort_keys=True,
            )
        )
