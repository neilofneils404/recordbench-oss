"""Synthetic admitted-source controls exercise real save and export routes."""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import time
import zipfile
from email.message import EmailMessage
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from case_intelligence.workbench import create_workbench_app
from case_intelligence.pilot_uploads import PilotStore
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore
from case_intelligence.derived_text import presentation_text
from tests.test_review_tools import CleanScanner

ACTOR = "development-taylor-morgan"
PASSAGE = "Pump Cedar\x1a\x1b remained sealed. The reviewer saw café and a\u200db."


class SourceEcho:
    available = True

    def generate(self, **kwargs):
        evidence = kwargs["evidence"][0]
        return {"answerable": True, "claims": [{"text": evidence.excerpt,
                "evidence_ids": [evidence.evidence_id]}], "limitation": None, "missing_information": ""}


@pytest.fixture
def source_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_STORAGE_RESERVE_GIB", "0")
    with TestClient(create_workbench_app(tmp_path / "runtime", generator=SourceEcho(),
                                       auth_mode="test", malware_scanner=CleanScanner(),
                                       malware_scan_mode="extended"), raise_server_exceptions=False) as client:
        response = client.post("/matters", data={"name": "Synthetic control passages",
                               "descriptor": "Synthetic R4 regression"}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        response = client.post(f"/matters/{slug}/uploads",
            files=[("files", ("synthetic-controls.txt", PASSAGE.encode(), "text/plain"))])
        assert response.status_code == 200
        document = next(iter(bench.source_store(matter).documents.values()))
        search = client.get(f"/matters/{slug}", params={"mode": "search", "q": "Pump Cedar"})
        token = re.search(rf"/matters/{slug}\?support=([0-9a-f]{{40}})", search.text)
        assert token, search.text
        yield client, bench, matter, document, token.group(1)


def wait_answer(client, payload):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(payload["status_url"]).json()
        if result["state"] in {"succeeded", "failed"}:
            return result
        time.sleep(.01)
    pytest.fail("Synthetic answer did not finish")


def test_admitted_controls_save_source_note(source_workspace):
    client, bench, matter, document, token = source_workspace
    response = client.post(f"/matters/{matter.slug}/notebook/from-support/{token}", follow_redirects=False)
    assert response.status_code == 303, response.text
    assert "error=" not in response.headers["location"]
    note = bench.workspace.all_notebook_items(matter.matter_id, ACTOR)[0]
    assert "Cedar   remained" in note.body and "a\u200db" in note.body
    reference = bench.workspace.notebook_references(matter.matter_id, ACTOR, note.item_id)[0]
    assert reference.excerpt == document.parsed_units()[0].text
    assert reference.excerpt_digest == document.parsed_units()[0].excerpt_digest
    original = bench.source_store(matter).source_path(document.document_id, verify_digest=True).read_bytes()
    assert original == PASSAGE.encode()
    assert document.parsed_units()[0].excerpt_digest == hashlib.sha256(PASSAGE.encode()).hexdigest()
    page = client.get(f"/matters/{matter.slug}", params={"support": token})
    assert page.status_code == 200 and "\x1a" not in page.text and "\x1b" not in page.text
    assert "a\u200db" in page.text


def test_admitted_controls_generated_answer_completes(source_workspace):
    client, bench, matter, _, _ = source_workspace
    conversation = bench.workspace.get_conversation(matter.matter_id)
    for suffix in ("a", "b"):
        response = client.post(f"/matters/{matter.slug}/ask", data={
            "conversation": conversation.conversation_id, "question": "What happened to Pump Cedar?",
            "request_key": "answer-request-" + suffix * 32}, headers={"Accept": "application/json"})
        assert response.status_code == 202, response.text
        result = wait_answer(client, response.json())
        assert result["state"] == "succeeded", result
    message = bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1]
    assert message.payload["claims"][0]["citations"][0]["excerpt_digest"] == hashlib.sha256(PASSAGE.encode()).hexdigest()
    assert "\x1a" not in message.content and "\x1b" not in message.content
    saved = client.post(f"/matters/{matter.slug}/conversations/{conversation.conversation_id}/"
                       f"messages/{message.message_id}/notebook/claims/0", follow_redirects=False)
    assert saved.status_code == 303 and "error=" not in saved.headers["location"]


def test_older_saved_answer_controls_create_report(source_workspace):
    client, bench, matter, document, _ = source_workspace
    conversation = bench.workspace.get_conversation(matter.matter_id)
    citation = bench._citation(matter, bench._candidate(matter, document, document.parsed_units()[0], 1))
    # Older messages can already retain controls in JSON citation/claim payloads
    # even when the message's top-level prose passed the old strict validator.
    message = bench.workspace.append_message(matter.matter_id, conversation.conversation_id, "assistant",
        "The reviewer described Pump Cedar.", {"kind": "generated", "claims": [{"text": PASSAGE,
            "citations": [citation.staff_payload()]}]})
    report = bench.workspace.create_report(matter.matter_id, ACTOR, "Synthetic control report")
    response = client.post(f"/matters/{matter.slug}/reports/{report.report_id}/from-answer/"
                           f"{conversation.conversation_id}/{message.message_id}",
                           data={"expected_status": report.status}, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1] == message
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    assert len(sections) == 1
    refs = bench.workspace.report_citations(matter.matter_id, report.report_id, sections[0].section_id)
    assert refs[0].excerpt == PASSAGE
    for route in (f"reports/{report.report_id}/export", "notebook/export",
                  f"conversations/{conversation.conversation_id}/export"):
        # Empty notebook still exports; the Report/conversation include controls.
        response = client.get(f"/matters/{matter.slug}/{route}", params={"format": "docx"})
        assert response.status_code == 200, response.text[:200]
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for path in archive.namelist():
                if path.endswith((".xml", ".rels")):
                    ElementTree.fromstring(archive.read(path))
    page = client.get(f"/matters/{matter.slug}", params={"conversation": conversation.conversation_id})
    assert page.status_code == 200 and "\x1a" not in page.text and "\x1b" not in page.text
    assert bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1] == message


def test_source_save_validation_error_returns_to_support(source_workspace, monkeypatch):
    client, bench, matter, _, token = source_workspace
    def reject(*args, **kwargs):
        raise WorkspaceProblem("Synthetic save limit reached.")
    monkeypatch.setattr(bench, "save_support_to_notebook", reject)
    response = client.post(f"/matters/{matter.slug}/notebook/from-support/{token}", follow_redirects=True)
    assert response.status_code == 200
    assert "Synthetic save limit reached" in response.text and "source remains available" in response.text


def test_control_policy_bounds_unicode_and_exact_source_basis():
    raw = " \x00A\x1aB\x1bC\x0cD\x7fE\x85F\ud800G\ufffeH\uffff \t\r\n café e\u0301 a\u200cb\u200dc\u2060d "
    projected = presentation_text(raw)
    assert len(projected) == len(raw)
    assert "A B C D E F G H " in projected
    assert "\t\r\n café e\u0301 a\u200cb\u200dc\u2060d" in projected
    source = " \tA\x1aB\x1bC e\u0301\r\n "
    assert WorkspaceStore._source_text(source, label="Excerpt", maximum=100) == source
    with pytest.raises(WorkspaceProblem, match="too long"):
        WorkspaceStore._derived_text("\x1b" * 101, label="Details", maximum=100)
    with pytest.raises(WorkspaceProblem, match="unsupported"):
        WorkspaceStore._safe_text("actor\u200dname", label="Identity", maximum=100)
    with pytest.raises(WorkspaceProblem, match="invalid Unicode"):
        WorkspaceStore._source_text("invalid\ud800", label="Excerpt", maximum=100)


def test_control_text_backup_clean_restore(source_workspace, tmp_path):
    client, bench, matter, document, token = source_workspace
    response = client.post(f"/matters/{matter.slug}/notebook/from-support/{token}", follow_redirects=False)
    assert response.status_code == 303
    note = bench.workspace.all_notebook_items(matter.matter_id, ACTOR)[0]
    report = bench.workspace.create_report(matter.matter_id, ACTOR, "Synthetic restored report")
    bench.add_notebook_item_to_report(matter, ACTOR, report.report_id, note.item_id, expected_status=report.status)
    before_refs = bench.workspace.notebook_references(matter.matter_id, ACTOR, note.item_id)
    before_sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    backup_path = tmp_path / "control-backup.sqlite"
    with sqlite3.connect(backup_path) as target, bench.workspace._lock:
        bench.workspace.connection.backup(target)
    restore_path = tmp_path / "clean-restore.sqlite"
    restore_path.write_bytes(backup_path.read_bytes())
    restored = WorkspaceStore(restore_path)
    try:
        assert restored.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.notebook_item(matter.matter_id, ACTOR, note.item_id) == note
        assert restored.notebook_references(matter.matter_id, ACTOR, note.item_id) == before_refs
        assert restored.report_sections(matter.matter_id, report.report_id) == before_sections
        citations = restored.report_citations(matter.matter_id, report.report_id, before_sections[0].section_id)
        assert citations[0].excerpt == PASSAGE
        assert before_refs[0].excerpt_digest == document.parsed_units()[0].excerpt_digest
    finally:
        restored.close()


@pytest.mark.parametrize("kind", ["csv", "email"])
def test_csv_and_email_control_passages_save_with_originals(source_workspace, kind):
    client, bench, matter, _, _ = source_workspace
    if kind == "csv":
        name, media_type = "synthetic-controls.csv", "text/csv"
        original = ("observation\n" + PASSAGE + "\n").encode()
    else:
        name, media_type = "synthetic-controls.eml", "message/rfc822"
        email = EmailMessage()
        email["From"] = "sender@example.invalid"
        email["To"] = "reviewer@example.invalid"
        email["Subject"] = "Synthetic control passage"
        email.set_content(PASSAGE, cte="base64")
        original = email.as_bytes()
    response = client.post(f"/matters/{matter.slug}/uploads",
        files=[("files", (name, original, media_type))])
    assert response.status_code == 200
    document = next(d for d in bench.source_store(matter).documents.values() if d.display_name == name)
    assert document.state == "ready", document.message
    ordinal, unit = next((n, unit) for n, unit in enumerate(document.parsed_units(), 1) if "Cedar" in unit.text)
    assert "\x1a" in unit.text and "\x1b" in unit.text
    citation = bench._citation(matter, bench._candidate(matter, document, unit, ordinal))
    response = client.post(f"/matters/{matter.slug}/notebook/from-support/{citation.support_token}", follow_redirects=False)
    assert response.status_code == 303 and "error=" not in response.headers["location"]
    note = bench.workspace.all_notebook_items(matter.matter_id, ACTOR)[0]
    reference = bench.workspace.notebook_references(matter.matter_id, ACTOR, note.item_id)[0]
    assert reference.excerpt == unit.text
    assert reference.excerpt_digest == unit.excerpt_digest
    assert bench.source_store(matter).source_path(document.document_id, verify_digest=True).read_bytes() == original
    assert document.digest == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85"])
def test_existing_txt_line_separator_basis_survives_restart_and_note_save(source_workspace, separator):
    """Presentation must not silently reinterpret an existing extraction basis."""
    client, bench, matter, _, _ = source_workspace
    raw = f"Pump Cedar{separator}remained sealed.\tCafé a\u200db."
    original = raw.encode()
    response = client.post(f"/matters/{matter.slug}/uploads", files=[
        ("files", ("synthetic-line-boundary.txt", original, "text/plain")),
    ])
    assert response.status_code == 200
    sources = bench.source_store(matter)
    document = next(d for d in sources.documents.values() if d.display_name == "synthetic-line-boundary.txt")
    expected = raw.replace(separator, "\n")
    unit = document.parsed_units()[0]
    assert unit.text == expected
    assert (unit.line_start, unit.line_end, document.page_count) == (1, 2, 2)
    assert unit.excerpt_digest == hashlib.sha256(expected.encode()).hexdigest()
    assert document.digest == hashlib.sha256(original).hexdigest()
    reopened = PilotStore(sources.root)
    try:
        historical = reopened.get(document.document_id)
        assert historical.version_id == document.version_id
        assert historical.digest == document.digest
        assert historical.parsed_units() == document.parsed_units()
        assert reopened.source_path(document.document_id, verify_digest=True).read_bytes() == original
    finally:
        reopened.close()
    citation = bench._citation(matter, bench._candidate(matter, document, unit, 1))
    response = client.post(f"/matters/{matter.slug}/notebook/from-support/{citation.support_token}", follow_redirects=False)
    assert response.status_code == 303 and "error=" not in response.headers["location"]
    note = bench.workspace.all_notebook_items(matter.matter_id, ACTOR)[0]
    reference = bench.workspace.notebook_references(matter.matter_id, ACTOR, note.item_id)[0]
    assert reference.excerpt == expected
    assert reference.excerpt_digest == unit.excerpt_digest
    assert reference.support_token == citation.support_token
