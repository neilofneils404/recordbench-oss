"""Generated limitation presentation never changes its exact cited source basis."""
from __future__ import annotations

import html
import io

import pytest

from case_intelligence.generation import LEGACY_VERIFICATION_OMISSION_NOTICE as OLD, VERIFICATION_OMISSION_NOTICE as NEW
from tests.test_answer_cited_context import append_answer, context_path, saved_reference
from tests.test_saved_answer_note_preview import STATEMENT, long_answer  # noqa: F401


def raw_payload(fixture, message):
    _, bench, _, _, _, _, _ = fixture
    return bench.workspace.connection.execute(
        "SELECT payload_json FROM workbench_message WHERE message_id=?", (message.message_id,)
    ).fetchone()[0]


def assert_comparison(fixture, message, expected, *, source=None):
    client, bench, matter, document, citation, _, _ = fixture
    if source is not None:
        document, citation = source
    before = raw_payload(fixture, message)
    original = bench.source_store(matter).source_path(document.document_id).read_bytes()
    path = context_path(fixture, message=message, passage="limitation")
    response = client.get(path, params={"format": "json"})
    assert response.status_code == 200
    value = response.json()
    assert value["state"] == "available"
    assert value["passage_text"] == expected
    assert value["excerpt"] == citation.excerpt[:6_000]
    assert value["source_version_id"] == citation.source_version_id
    assert value["excerpt_digest"] == citation.excerpt_digest
    assert response.headers["cache-control"] == "no-store"
    page = client.get(path)
    assert page.status_code == 200 and expected in html.unescape(page.text)
    assert raw_payload(fixture, message) == before
    assert bench.source_store(matter).source_path(document.document_id).read_bytes() == original
    return value


@pytest.mark.parametrize("explicit", [False, True])
def test_historical_limitation_comparison_projects_service_notice_after_merge(long_answer, explicit):
    client, bench, matter, _, _, conversation, original = long_answer
    reference = original.payload["claims"][0]["citations"][0]
    qualification = {"text": STATEMENT, "citations": [reference]}
    payload = {**original.payload, "limitation": {"text": STATEMENT + " " + OLD, "citations": [reference]},
               "omitted_claims": 1}
    if explicit:
        payload.update(source_limitation=qualification, verification_notice=OLD)
    else:
        payload.pop("source_limitation", None)
        payload.pop("verification_notice", None)
    message = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        "assistant", original.content, payload)
    page = client.get(f"/matters/{matter.slug}/assistant")
    assert NEW in page.text and OLD not in page.text
    assert "cited-context/limitation/0" in page.text
    assert "Compare cited context" in page.text
    assert_comparison(long_answer, message, STATEMENT + " " + NEW)


@pytest.mark.parametrize("case", ["current", "custom", "unmarked", "source_quote"])
def test_limitation_context_preserves_current_custom_and_sourced_words(long_answer, case):
    _, bench, matter, _, _, _, original = long_answer
    reference = original.payload["claims"][0]["citations"][0]
    qualification = {"text": STATEMENT, "citations": [reference]}
    source = None
    if case == "source_quote":
        source_text = STATEMENT + ' The source quotes "' + OLD + '".'
        document, _ = bench.source_store(matter).store_stream("Synthetic quoted notice.txt", "text/plain",
            io.BytesIO(source_text.encode()))
        bench._sync_source_catalog(matter, [document])
        citation = bench._citation(matter, bench._candidate(matter, document, document.parsed_units()[0], 1))
        reference = saved_reference(bench, citation)
        qualification = {"text": source_text, "citations": [reference]}
        source = document, citation
    text = qualification["text"] + " " + (NEW if case == "current" else OLD)
    if case == "custom":
        text += " Custom annotation."
    payload = {"limitation": {"text": text, "citations": [reference]}, "omitted_claims": 0}
    if case != "unmarked":
        payload.update(source_limitation=qualification, verification_notice=NEW if case == "current" else OLD)
    expected = qualification["text"] + " " + NEW if case == "source_quote" else text
    message = append_answer(long_answer, **payload)
    assert_comparison(long_answer, message, expected, source=source)


def test_omission_projection_does_not_rewrite_claims_or_admit_manual_messages(long_answer):
    client, _, _, _, _, _, original = long_answer
    claim = {**original.payload["claims"][0], "text": OLD}
    message = append_answer(long_answer, claims=[claim])
    before = raw_payload(long_answer, message)
    response = client.get(context_path(long_answer, message=message), params={"format": "json"})
    assert response.status_code == 200 and response.json()["passage_text"] == OLD
    assert raw_payload(long_answer, message) == before
    manual = append_answer(long_answer, kind="manual", limitation={"text": OLD, "citations": claim["citations"]})
    before = raw_payload(long_answer, manual)
    for fmt in ("html", "json"):
        response = client.get(context_path(long_answer, message=manual, passage="limitation"), params={"format": fmt})
        assert response.status_code == 404
    assert raw_payload(long_answer, manual) == before


def test_projected_limitation_keeps_raw_citation_validation_and_unavailable_state(long_answer):
    client, _, _, _, _, _, original = long_answer
    reference = {**original.payload["claims"][0]["citations"][0], "excerpt_digest": "f" * 64}
    qualification = {"text": STATEMENT, "citations": [reference]}
    message = append_answer(long_answer,
        limitation={"text": STATEMENT + " " + OLD, "citations": [reference]},
        source_limitation=qualification, verification_notice=OLD, omitted_claims=1)
    before = raw_payload(long_answer, message)
    response = client.get(context_path(long_answer, message=message, passage="limitation"), params={"format": "json"})
    assert response.status_code == 200
    value = response.json()
    assert value["passage_text"] == STATEMENT + " " + NEW
    assert value["state"] == "unavailable" and value["excerpt"] == value["source_href"] == ""
    assert value["excerpt_digest"] == "f" * 64
    assert raw_payload(long_answer, message) == before
