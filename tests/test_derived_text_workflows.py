"""Synthetic derived-text saves keep the exact original citation basis."""
from __future__ import annotations

import copy
import io
import json
import time

from fastapi.testclient import TestClient
import pytest

from case_intelligence.answer_jobs import AnswerCoordinator, AnswerResult
from case_intelligence.generation import EvidenceItem, GroundedGenerationService
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceProblem


ACTOR = "development-taylor-morgan"
RAW = "Synthetic Cedar\x1arecorded 18 psi\x1bduring the test. Joined \u200d and \u200c text."
DISPLAY = RAW.replace("\x1a", " ").replace("\x1b", " ")


class SourceEcho:
    available = True

    def generate(self, *, evidence, **kwargs):
        return {"answerable": True,
                "claims": [{"text": evidence[0].excerpt,
                            "evidence_ids": [evidence[0].evidence_id]}],
                "limitation": None, "missing_information": ""}


@pytest.fixture
def source_workflow(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test",
        storage_policy=StoragePolicy(reserve_bytes=0), generator=SourceEcho())
    with TestClient(app):
        bench = app.state.workbench
        for coordinator in (bench.answers, bench.research, bench.full_review):
            coordinator.close()
        matter = bench.create_matter("Synthetic derived text workflows", "", ACTOR)
        source_store = bench.source_store(matter)
        document, _ = source_store.store_stream("Synthetic Cedar.txt", "text/plain",
                                               io.BytesIO(RAW.encode()))
        bench._sync_source_catalog(matter, [document])
        unit = document.parsed_units()[0]
        citation = bench._citation(matter, bench._candidate(matter, document, unit, 1))
        assert citation.excerpt == RAW
        yield bench, matter, citation


def test_research_summary_saves_without_rewriting_verified_claim_or_original(source_workflow):
    bench, matter, citation = source_workflow
    workspace = bench.workspace
    conversation = workspace.get_conversation(matter.matter_id)
    queued, _ = workspace.queue_research_job(matter.matter_id, ACTOR,
        "What does Cedar record?", "Synthetic research", "research-request-" + "a" * 32,
        conversation_id=conversation.conversation_id)
    job = workspace.claim_research_job("synthetic-text-worker")
    assert job.job_id == queued.job_id
    original = bench._saved_answer_citation_payload(citation)
    answer = GroundedGenerationService(SourceEcho()).answer("What does Cedar record?",
        (EvidenceItem("S1", citation.source_name, citation.location, citation.excerpt),))
    assert answer.claims[0].text == RAW
    payload = bench._answer_payload(answer, {"S1": citation})
    result = {"summary": answer.text, "answer": payload, "evidence": [original]}

    completed = workspace.finish_research_job(job.job_id, result)
    assert completed.state == "succeeded"
    message = workspace.messages(matter.matter_id, conversation.conversation_id)[-1]
    assert DISPLAY in message.content
    assert message.payload["claims"][0]["text"] == RAW
    assert message.payload["claims"][0]["citations"][0] == original
    assert completed.result == result
    assert workspace.finish_research_job(job.job_id, result).result_message_id == message.message_id


def test_every_source_decision_saves_prose_and_keeps_citation_basis(source_workflow):
    bench, matter, citation = source_workflow
    workspace = bench.workspace
    _, criterion = workspace.create_review_criterion(matter.matter_id, ACTOR,
        title="Cedar reading", instructions="Include a source with a Cedar reading.")
    queued = workspace.queue_review_run(matter.matter_id, ACTOR,
                                        criterion.criterion_version_id, run_kind="full")
    run = workspace.claim_review_run("synthetic-review-worker")
    assert run.run_id == queued.run_id
    original = bench._workflow_citation_payload(citation)
    workspace.record_review_decision(run.run_id, citation.document_id,
        decision="included", rationale=RAW, citations=[original], expected_attempt=run.attempts)
    saved = workspace.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)[0]
    assert saved.machine_decision == "included"
    assert saved.rationale == DISPLAY
    assert list(saved.citations) == [original]
    assert saved.source_version_id == citation.source_version_id
    assert workspace.finish_review_run(run.run_id).state == "succeeded"


def test_analysis_saves_derived_prose_and_exact_raw_references(source_workflow):
    bench, matter, citation = source_workflow
    workspace = bench.workspace
    reference = bench.notebook_reference_from_support(matter, citation.support_token)
    # Two independently attributed synthetic sources form the finding.
    document, _ = bench.source_store(matter).store_stream("Synthetic second Cedar.txt",
        "text/plain", io.BytesIO((RAW + " Separate synthetic account.").encode()))
    bench._sync_source_catalog(matter, [document])
    unit = document.parsed_units()[0]
    other = bench._citation(matter, bench._candidate(matter, document, unit, 1))
    other_reference = bench.notebook_reference_from_support(matter, other.support_token)
    run = workspace.start_analysis_run(matter.matter_id, ACTOR)
    completed = workspace.complete_analysis_run(run.analysis_id, matter.matter_id, ACTOR,
        source_count=2, unit_count=2, entity_count=0, capped=False,
        findings=[{"kind": "comparison", "signature": "a" * 64,
                   "title": "Synthetic\x1aCedar comparison", "summary": RAW,
                   "references": [reference, other_reference]}])
    assert completed.state == "complete"
    finding = workspace.review_findings(matter.matter_id)[0]
    assert finding.title == "Synthetic Cedar comparison"
    assert finding.summary == DISPLAY
    saved = workspace.review_finding_references(matter.matter_id, finding.finding_id)
    for record, expected in zip(saved, (reference, other_reference)):
        assert record.excerpt == expected["excerpt"]
        assert record.excerpt_digest == expected["excerpt_digest"]
        assert record.support_token == expected["support_token"]
        assert record.source_version_id == expected["source_version_id"]


def test_background_save_failure_preserves_actionable_workspace_problem(source_workflow):
    bench, matter, _ = source_workflow
    workspace = bench.workspace
    conversation = workspace.get_conversation(matter.matter_id)
    queued, _ = workspace.queue_answer_job(matter.matter_id, conversation.conversation_id,
        ACTOR, "What does Cedar record?", "answer-request-" + "b" * 32)
    coordinator = AnswerCoordinator(workspace,
        process=lambda *_: AnswerResult("x" * 20_001, {"kind": "generated"}), workers=1)
    try:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            saved = workspace.get_answer_job(matter.matter_id, ACTOR, queued.job_id)
            if saved.state == "failed":
                break
            time.sleep(.01)
        assert saved.state == "failed"
        assert "Answer is too long" in saved.message
        assert "Shorten the text and save again" in saved.message
        assert [item.role for item in workspace.messages(matter.matter_id,
            conversation.conversation_id)] == ["user"]
    finally:
        coordinator.close()


def _oversized_serialized_payload():
    # The repository accepts bounded serialized result mappings. JSON escapes
    # can exceed that limit even when the displayed prose is short.
    payload = {"kind": "generated", "source_details": "\x1a\x1b" * 8_334}
    assert len(payload["source_details"]) < 20_000
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) > 100_000
    return payload


def test_synchronous_payload_limit_is_actionable_and_atomic(source_workflow):
    bench, matter, _ = source_workflow
    workspace = bench.workspace
    conversation = workspace.get_conversation(matter.matter_id)
    payload = _oversized_serialized_payload()
    original = copy.deepcopy(payload)
    before_messages = workspace.messages(matter.matter_id, conversation.conversation_id)
    with pytest.raises(WorkspaceProblem, match="Ask a narrower question or select fewer sources"):
        workspace.append_message(matter.matter_id, conversation.conversation_id,
            "assistant", "Synthetic short answer.", payload)
    assert workspace.messages(matter.matter_id, conversation.conversation_id) == before_messages
    assert workspace.get_conversation(matter.matter_id, conversation.conversation_id) == conversation
    assert payload == original


def test_background_payload_limit_retains_actionable_error_without_partial_answer(source_workflow):
    bench, matter, _ = source_workflow
    workspace = bench.workspace
    conversation = workspace.get_conversation(matter.matter_id)
    queued, _ = workspace.queue_answer_job(matter.matter_id, conversation.conversation_id,
        ACTOR, "What does Cedar record?", "answer-request-" + "c" * 32)
    before_messages = workspace.messages(matter.matter_id, conversation.conversation_id)
    before_conversation = workspace.get_conversation(matter.matter_id, conversation.conversation_id)
    payload = _oversized_serialized_payload()
    original = copy.deepcopy(payload)
    coordinator = AnswerCoordinator(workspace,
        process=lambda *_: AnswerResult("Synthetic short answer.", payload), workers=1)
    try:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            saved = workspace.get_answer_job(matter.matter_id, ACTOR, queued.job_id)
            if saved.state == "failed":
                break
            time.sleep(.01)
        assert saved.state == "failed"
        assert "source details exceed the save limit" in saved.message
        assert "Ask a narrower question or select fewer sources" in saved.message
        assert "try again" not in saved.message
        assert saved.result_message_id is None
        assert workspace.messages(matter.matter_id, conversation.conversation_id) == before_messages
        assert workspace.get_conversation(matter.matter_id, conversation.conversation_id) == before_conversation
        assert payload == original
    finally:
        coordinator.close()
