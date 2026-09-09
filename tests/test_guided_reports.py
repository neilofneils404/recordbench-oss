"""Synthetic browser-facing report compilation and document lifecycle."""
from __future__ import annotations

import io
import threading
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import GroundedGenerationService
from tests.test_report_compilation import SourceEchoClient
from tests.test_report_review_basis import ACTOR, saved_research, workspace
from tests.test_matter_management import OWNER, OTHER, _app, _create_matter, _csrf, _headers


def queue(client, matter, selections, *, kind="timeline", topic="", key="synthetic-report-request"):
    response = client.post(f"/matters/{matter.slug}/reports/compile", data={
        "kind": kind, "topic": topic, "selection": selections, "request_key": key,
    }, follow_redirects=False)
    assert response.status_code == 303, response.text
    return parse_qs(urlparse(response.headers["location"]).query)["job"][0]


def finished(client, matter, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/matters/{matter.slug}/reports/compile/{job_id}/status")
        assert response.status_code == 200
        state = response.json()
        if state["terminal"]:
            return state
        time.sleep(.02)
    raise AssertionError("Synthetic report did not finish")


@pytest.mark.parametrize("kind", ["timeline", "entities", "topic"])
def test_compile_saved_research_to_readable_editable_exportable_document(workspace, kind):
    client, bench, matter = workspace
    bench.generator = GroundedGenerationService(SourceEchoClient())
    research, document = saved_research(bench, matter)
    selected = f"research:{research.job_id}"
    composer = client.get(f"/matters/{matter.slug}/reports/new?from={selected}")
    assert composer.status_code == 200 and 'value="' + selected + '" checked' in composer.text
    job_id = queue(client, matter, [selected], kind=kind, topic="bicycle arrival", key="synthetic-report-" + kind)
    result = finished(client, matter, job_id)
    assert result["state"] == "succeeded", result
    page = client.get(result["result_url"])
    assert page.status_code == 200 and 'class="report-reading-page"' in page.text
    assert 'textarea name="body"' not in page.text
    report = bench.workspace.reports(matter.matter_id, ACTOR)[0]
    section = next(item for item in bench.workspace.report_sections(matter.matter_id, report.report_id)
                   if bench.workspace.report_citations(matter.matter_id, report.report_id, item.section_id))
    edit = client.get(result["result_url"] + "&edit=true")
    assert edit.status_code == 200 and 'name="body"' in edit.text
    marker = "Human reviewer requests the missing gate log."
    response = client.post(f"/matters/{matter.slug}/reports/{report.report_id}/sections/{section.section_id}", data={
        "heading": section.heading, "body": section.body.split("\n\nReview basis:\n", 1)[0] + "\n" + marker,
        "expected_updated_at": section.updated_at, "expected_status": report.status,
    }, follow_redirects=False)
    assert response.status_code == 303
    retained = next(item for item in bench.workspace.report_sections(matter.matter_id, report.report_id) if item.section_id == section.section_id)
    assert retained.body.split("\n\nReview basis:\n", 1)[1] == section.body.split("\n\nReview basis:\n", 1)[1]
    for fmt in ("markdown", "docx"):
        exported = client.get(f"/matters/{matter.slug}/reports/{report.report_id}/export?format={fmt}")
        assert exported.status_code == 200, exported.text[:100]
        if fmt == "docx":
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                text = archive.read("word/document.xml").decode()
        else:
            text = exported.text
        assert marker in text and document.display_name in text and "Compilation coverage" in text
    assert queue(client, matter, [selected], kind=kind, topic="bicycle arrival", key="synthetic-report-" + kind) == job_id
    assert len(bench.workspace.reports(matter.matter_id, ACTOR)) == 1


def test_changed_selected_work_during_generation_fails_without_orphan_and_retries(workspace):
    client, bench, matter = workspace
    entered, release = threading.Event(), threading.Event()
    class BlockingClient(SourceEchoClient):
        def generate(self, **kwargs):
            entered.set()
            assert release.wait(8)
            return super().generate(**kwargs)
    bench.generator = GroundedGenerationService(BlockingClient())
    research, _ = saved_research(bench, matter)
    note, _ = bench.workspace.create_notebook_item(matter.matter_id, ACTOR,
        item_type="event", status="confirmed", title="Bicycle arrival", body="Reviewer observed the arrival.")
    job_id = queue(client, matter, ["notes:active", f"research:{research.job_id}"])
    try:
        assert entered.wait(5)
        bench.workspace.update_notebook_item(matter.matter_id, ACTOR, note.item_id,
            expected_updated_at=note.updated_at, item_type="event", status="disputed",
            title=note.title, body="The time of arrival is now disputed.")
    finally:
        release.set()
    result = finished(client, matter, job_id)
    assert result["state"] == "failed" and "changed" in result["message"]
    assert bench.workspace.reports(matter.matter_id, ACTOR) == ()
    retry = client.post(f"/matters/{matter.slug}/reports/compile/{job_id}/retry", follow_redirects=False)
    assert retry.status_code == 303
    assert finished(client, matter, job_id)["state"] == "succeeded"
    assert len(bench.workspace.reports(matter.matter_id, ACTOR)) == 1


def test_queued_cancel_and_missing_material_never_create_empty_reports(workspace):
    client, bench, matter = workspace
    bench.report_compilation.coordinator.close()
    job_id = queue(client, matter, ["notes:active"])
    response = client.post(f"/matters/{matter.slug}/reports/compile/{job_id}/cancel", follow_redirects=False)
    assert response.status_code == 303
    assert finished(client, matter, job_id)["state"] == "cancelled"
    assert not bench.workspace.reports(matter.matter_id, ACTOR)
    assert client.get(f"/matters/{matter.slug}/reports/new").status_code == 200


def test_compilation_routes_require_membership_and_csrf(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_STORAGE_RESERVE_GIB", "0")
    app = _app(tmp_path)
    with TestClient(app, base_url="https://testserver") as client:
        token = _csrf(client.get('/matters/new', headers=_headers(OWNER)).text)
        slug = _create_matter(client, principal=OWNER, csrf_token=token, name="Synthetic private report")
        data = {"kind": "timeline", "selection": ["notes:active"], "request_key": "synthetic-secure-request"}
        path = f"/matters/{slug}/reports/compile"
        assert client.post(path, data={**data, "csrf_token": "wrong"}, headers=_headers(OWNER)).status_code == 403
        assert client.get(f"/matters/{slug}/reports/new", headers=_headers(OTHER)).status_code == 404
        assert client.post(path, data={**data, "csrf_token": token}, headers=_headers(OTHER)).status_code in {403, 404}
        assert not app.state.workbench.workspace.connection.execute("SELECT 1 FROM workbench_report_compilation_job").fetchone()


def test_long_canonical_source_support_survives_compilation_and_both_exports(workspace):
    client, bench, matter = workspace
    full_text = "A synthetic account " + "bicycle " * 900 + "END-OF-CANONICAL-SOURCE."
    document, _ = bench.source_store(matter).store_stream('synthetic-long-source.txt', 'text/plain', io.BytesIO(full_text.encode()))
    unit = document.parsed_units()[0]
    assert len(unit.text) > 6000
    candidate = bench._candidate(matter, document, unit, 1)
    reference = bench._workflow_citation_payload(bench._citation(matter, candidate))
    reference.update(chunk_id=candidate.chunk_id, unit_number=unit.number,
        excerpt_digest=unit.excerpt_digest, excerpt=unit.text[:6000])
    note, _ = bench.workspace.create_notebook_item(matter.matter_id, ACTOR, item_type='event',
        status='confirmed', title='Long account retained', body='Human reviewer flags the long account for comparison.', references=[reference])
    result = finished(client, matter, queue(client, matter, [f'note:{note.item_id}'], key='synthetic-long-canonical'))
    assert result['state'] == 'succeeded', result
    report = bench.workspace.reports(matter.matter_id, ACTOR)[0]
    citations = [citation for section in bench.workspace.report_sections(matter.matter_id, report.report_id)
                 for citation in bench.workspace.report_citations(matter.matter_id, report.report_id, section.section_id)]
    assert any(citation.excerpt == unit.text for citation in citations)
    for fmt in ('markdown', 'docx'):
        response = client.get(f'/matters/{matter.slug}/reports/{report.report_id}/export?format={fmt}')
        assert response.status_code == 200, response.text[:100]
        if fmt == 'docx':
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                text = archive.read('word/document.xml').decode()
        else:
            text = response.text
        assert 'END-OF-CANONICAL-SOURCE.' in text
