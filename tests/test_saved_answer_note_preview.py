"""Long source Notes retain previews after validating the complete saved basis.

Fresh text and PCM fixtures use real answer persistence and source projection.
The controlled transcript transport and answer client do not evaluate ASR or
model quality. Report compilation continues to require a complete bounded unit.
"""
from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient
import pytest

from case_intelligence import report_materials
from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.report_materials import snapshot_report_materials
from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceProblem
from tests.test_saved_answer_report_support import CedarProcessor, synthetic_pcm


ACTOR = "development-taylor-morgan"
STATEMENT = "Pump Cedar showed an 18 psi reading while the reference gauge showed 12 psi."
LONG_TEXT = STATEMENT + " " + "Synthetic training padding. " * 250


class LongTranscriptProcessor(CedarProcessor):
    def transcript(self, owner, external_job_id):
        result = super().transcript(owner, external_job_id)
        result["segments"][0].update(text=LONG_TEXT, model_text=LONG_TEXT)
        return result


class ShortSupportedAnswer:
    available = True

    def generate(self, *, evidence, **kwargs):
        prefix = "The machine transcript appears to say that " if evidence[0].evidence_kind == "transcript" else ""
        return {"answerable": True,
            "claims": [{"text": prefix + STATEMENT, "evidence_ids": [evidence[0].evidence_id]}],
            "limitation": None, "missing_information": ""}


@pytest.fixture
def long_answer(tmp_path, monkeypatch, request):
    kind = getattr(request, "param", "document")
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test",
        storage_policy=StoragePolicy(reserve_bytes=0), generator=ShortSupportedAnswer(),
        media_processor=LongTranscriptProcessor(), media_poll_seconds=.01)
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.answers.close()
        bench.research.close()
        bench.full_review.close()
        matter = bench.create_matter("Synthetic long source Notes", "", ACTOR)
        store = bench.source_store(matter)
        if kind == "document":
            document, _ = store.store_stream("Synthetic pressure note.txt", "text/plain", io.BytesIO(LONG_TEXT.encode()))
            bench._sync_source_catalog(matter, [document])
        else:
            uploaded = client.post(f"/matters/{matter.slug}/uploads", files=[
                ("files", ("Synthetic pressure recording.wav", synthetic_pcm(), "audio/wav"))],
                follow_redirects=False)
            assert uploaded.status_code == 303
            deadline = time.monotonic() + 8
            continued = False
            while time.monotonic() < deadline:
                document = next(iter(store.documents.values()))
                if document.state == "ready":
                    break
                job = bench.workspace.media_job(matter.matter_id, document.document_id, document.version_id)
                if document.state == "needs_review" and job and job.preflight.get("inspection_id") and not continued:
                    # Authorize the generated silent carrier through the ordinary
                    # recording-check workflow before deterministic transcription.
                    response = client.post(f"/matters/{matter.slug}/sources/{store.action_token(document)}/recording-check",
                        data={"action": "continue", "inspection_id": job.preflight["inspection_id"]},
                        follow_redirects=False)
                    assert response.status_code == 303
                    continued = True
                time.sleep(.01)
            assert document.state == "ready", (document.state, document.message)
        unit = document.parsed_units()[0]
        assert len(unit.text) > 6_000
        citation = bench._citation(matter, bench._candidate(matter, document, unit, 1))
        monkeypatch.setattr(bench, "_answer_search", lambda *args, **kwargs: (citation,))
        conversation = bench.workspace.get_conversation(matter.matter_id)
        message = bench.ask(matter, conversation, "What pressure readings were recorded?")
        assert message.payload["kind"] == "generated" and len(message.payload["claims"]) == 1
        yield client, bench, matter, document, citation, conversation, message


def save_note(fixture, citation_index=None, message=None):
    _, bench, matter, _, _, conversation, saved = fixture
    return bench.save_answer_to_notebook(matter, ACTOR, conversation.conversation_id,
        (message or saved).message_id, 0, citation_index=citation_index)[0]


@pytest.mark.parametrize("long_answer", ["document", "transcript"], indirect=True)
@pytest.mark.parametrize("citation_index", [None, 0])
def test_long_saved_answer_keeps_notebook_preview_and_full_digest(long_answer, citation_index):
    client, bench, matter, _, citation, conversation, message = long_answer
    path = (f"/matters/{matter.slug}/conversations/{conversation.conversation_id}"
        f"/messages/{message.message_id}/notebook/claims/0")
    if citation_index == 0:
        path += "/citations/0"
    response = client.post(path, follow_redirects=False)
    assert response.status_code == 303 and "error=" not in response.headers["location"]
    notes = bench.workspace.all_notebook_items(matter.matter_id, ACTOR)
    assert len(notes) == 1
    note = notes[0]
    reference = bench.workspace.notebook_references(matter.matter_id, ACTOR, note.item_id)[0]
    assert reference.excerpt == citation.excerpt[:6_000].strip()
    assert (reference.document_id, reference.source_version_id, reference.location,
            reference.excerpt_digest, reference.support_token) == (
        citation.document_id, citation.source_version_id, citation.location,
        citation.excerpt_digest, citation.support_token)
    assert note.body == (reference.excerpt if citation_index == 0 else message.payload["claims"][0]["text"])
    assert reference.support_token in bench.available_notebook_support_tokens(matter, (reference,))
    assert client.get(citation.href).status_code == 200


@pytest.mark.parametrize("long_answer", ["transcript"], indirect=True)
@pytest.mark.parametrize("citation_index", [None, 0])
def test_transcript_change_beyond_notebook_preview_rejects_old_answer(long_answer, citation_index):
    client, bench, matter, document, citation, conversation, message = long_answer
    segment = bench.workspace.transcript_segments(matter.matter_id, document.document_id, document.version_id)[0]
    response = client.post(
        f"/matters/{matter.slug}/sources/{bench.source_store(matter).action_token(document)}/segments/{segment.segment_id}",
        data={"expected_revision": segment.current_revision, "text": LONG_TEXT + " Revised synthetic ending."},
        follow_redirects=False)
    assert response.status_code == 303 and "error=" not in response.headers["location"]
    current = bench.source_store(matter).get(document.document_id)
    changed = bench._citation(matter, bench._candidate(matter, current, current.parsed_units()[0], 1))
    assert changed.support_token == citation.support_token
    assert changed.excerpt[:6_000] == citation.excerpt[:6_000]
    assert changed.excerpt_digest != citation.excerpt_digest
    with pytest.raises(WorkspaceProblem, match="source support changed"):
        save_note(long_answer, citation_index)
    assert not bench.workspace.all_notebook_items(matter.matter_id, ACTOR)
    assert bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1] == message


@pytest.mark.parametrize("long_answer", ["document", "transcript"], indirect=True)
@pytest.mark.parametrize("field,replacement", [
    ("excerpt_digest", "f" * 64), ("source_version_id", "f" * 32),
    ("matter_id", "ci-matter-" + "f" * 32), ("excerpt", "A forged synthetic preview."),
    ("support_token", "f" * 40),
])
def test_long_note_preview_still_rejects_forged_saved_support(long_answer, field, replacement):
    _, bench, matter, _, _, conversation, original = long_answer
    claim = original.payload["claims"][0]
    reference = {**claim["citations"][0], field: replacement}
    saved = bench.workspace.append_message(matter.matter_id, conversation.conversation_id, "assistant",
        original.content, {**original.payload, "claims": [{**claim, "citations": [reference]}]})
    with pytest.raises(WorkspaceProblem, match="source support changed|conflicting source support"):
        save_note(long_answer, message=saved)
    assert not bench.workspace.all_notebook_items(matter.matter_id, ACTOR)


@pytest.mark.parametrize("long_answer", ["document", "transcript"], indirect=True)
def test_notebook_preview_does_not_relax_direct_or_compiled_report_limit(long_answer):
    _, bench, matter, _, _, conversation, message = long_answer
    note = save_note(long_answer)
    report = bench.workspace.create_report(matter.matter_id, ACTOR, "Synthetic bounded Report")
    with pytest.raises(WorkspaceProblem, match="6,000-character report limit"):
        bench.add_answer_to_report(matter, ACTOR, report.report_id, conversation.conversation_id,
            message.message_id, expected_status=report.status)
    for selection in (f"conversation:{conversation.conversation_id}", f"note:{note.item_id}"):
        with pytest.raises(WorkspaceProblem, match="6,000-character report limit"):
            with bench.source_store(matter).mutation_guard(), bench.workspace._lock:
                snapshot_report_materials(bench, matter, ACTOR, (selection,))
    assert not bench.workspace.report_sections(matter.matter_id, report.report_id)


@pytest.mark.parametrize("limit,value", [
    ("MAX_SOURCE_SCAN_CHARS", 6_000), ("MAX_SOURCE_SCAN_SERIALIZED_CHARS", 6_000),
    ("MAX_SOURCE_SCAN_RECORD_CHARS", 6_000),
    ("MAX_SOURCE_SCAN_UNITS", 0), ("MAX_SOURCE_SCAN_SECONDS", 0),
])
def test_notebook_preview_preserves_complete_source_scan_budgets(long_answer, monkeypatch, limit, value):
    _, bench, matter, _, _, _, _ = long_answer
    monkeypatch.setattr(report_materials, limit, value)
    with pytest.raises(WorkspaceProblem, match="source-validation limit"):
        save_note(long_answer)
    assert not bench.workspace.all_notebook_items(matter.matter_id, ACTOR)
