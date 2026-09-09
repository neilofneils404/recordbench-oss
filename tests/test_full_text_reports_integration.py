"""Synthetic full-text runs copied and compiled into bounded, source-checked Reports."""
from dataclasses import asdict
import hashlib
import io
import json
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

from case_intelligence.full_text_review import FullTextReviewLedger
from case_intelligence.generation import GroundedGenerationService
from case_intelligence.pilot_uploads import PilotDocument, PilotUnit
from tests.test_guided_reports import queue, finished
from tests.test_report_review_basis import ACTOR, workspace


class TextClassifier:
    available = True
    def classify_source(self, **kwargs):
        included = "amber bicycle" in kwargs["evidence"][0].excerpt
        return {"decision": "include" if included else "not_identified",
            "rationale": "The amber bicycle arrived." if included else "The criterion was not identified in this range.",
            "evidence_ids": ["S1"] if included else []}


def completed_text_run(bench, matter, texts, *, human_override=False):
    bench.full_review.close()
    bench.generator = GroundedGenerationService(TextClassifier())
    store = bench.source_store(matter)
    documents = []
    for index, text in enumerate(texts):
        document, _ = store.store_stream(f"synthetic-text-{index}.txt", "text/plain",
            io.BytesIO(f"Synthetic source admission {index}.".encode()))
        document.units = [asdict(PilotUnit(1, text,
            excerpt_digest=hashlib.sha256(text.encode()).hexdigest()))]
        store._write_units(document)
        documents.append(document)
    bench._sync_source_catalog(matter, documents)
    _, version = bench.workspace.create_review_criterion(matter.matter_id, ACTOR,
        title="Synthetic bicycle screening", instructions="Include the amber bicycle.")
    queued = bench.workspace.queue_review_run(matter.matter_id, ACTOR, version.criterion_version_id,
        run_kind="full", review_mode="full_text")
    run = bench.workspace.claim_review_run("synthetic-report-text-worker")
    assert run.run_id == queued.run_id
    while (decision := bench.workspace.next_review_decision(run.run_id)) is not None:
        outcome = bench._process_review_decision(run, decision, lambda: False)
        bench._record_review_decision(run, decision, outcome)
    completed = bench._finish_review_run(run)
    assert completed.state == "succeeded"
    if human_override:
        for document in documents:
            item = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, document.document_id)
            assert item.machine_decision == "excluded" and not item.citations
            bench.workspace.adjudicate_review_decision(matter.matter_id, ACTOR, run.run_id,
                document.document_id, human_decision="include", expected_updated_at=item.updated_at,
                note="Synthetic human disagreement needs review.")
    return completed, documents


def make_report(client, bench, matter, run, route):
    if route == "guided":
        job = queue(client, matter, [f"review:{run.run_id}"], key="synthetic-full-text-report")
        result = finished(client, matter, job)
        if result["state"] != "succeeded":
            return None, result["message"]
        report_id = parse_qs(urlparse(result["result_url"]).query)["report"][0]
    else:
        response = client.post(f"/matters/{matter.slug}/full-review/{run.run_id}/report", follow_redirects=False)
        assert response.status_code == 303, response.text
        values = parse_qs(urlparse(response.headers["location"]).query)
        if "error" in values:
            return None, values["error"][0]
        report_id = values["report"][0]
    return bench.workspace.report(matter.matter_id, report_id), ""


@pytest.mark.parametrize("route", ["direct", "guided"])
def test_actual_full_text_report_keeps_scope_support_and_exports_without_materializing(workspace, monkeypatch, route):
    client, bench, matter = workspace
    text = "The amber bicycle arrived. Synthetic complete supporting passage."
    run, documents = completed_text_run(bench, matter, [text])
    decision = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, documents[0].document_id)
    assert decision.citations and "excerpt" not in decision.citations[0]
    def no_materialization(*args):
        raise AssertionError("Full-text Report materialized a whole source")
    monkeypatch.setattr(PilotDocument, "parsed_units", no_materialization)
    report, error = make_report(client, bench, matter, run, route)
    assert report is not None, error
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    citations = [citation for section in sections for citation in bench.workspace.report_citations(matter.matter_id, report.report_id, section.section_id)]
    assert any(citation.excerpt == text for citation in citations)
    body = "\n".join(section.body for section in sections)
    assert "not the complete range ledger" in body
    assert "Each source was screened using selected passages" not in body
    for format_name in ("markdown", "docx"):
        result = client.get(f"/matters/{matter.slug}/reports/{report.report_id}/export?format={format_name}")
        assert result.status_code == 200, result.text[:100]
        if format_name == "docx":
            with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                exported = archive.read("word/document.xml").decode()
        else:
            exported = result.text
        assert text in exported and "not the complete range ledger" in exported


@pytest.mark.parametrize("route", ["direct", "guided"])
@pytest.mark.parametrize("tamper", ["actual_text", "version", "name"])
def test_uncited_full_text_human_override_rejects_changed_frozen_source(workspace, route, tamper):
    client, bench, matter = workspace
    run, documents = completed_text_run(bench, matter, ["A synthetic unrelated source."], human_override=True)
    document = documents[0]
    if tamper == "actual_text":
        path = bench.source_store(matter).derived / document.units_file
        value = json.loads(path.read_text())
        value["units"][0]["text"] += " Changed after review; digest metadata deliberately unchanged."
        path.write_text(json.dumps(value))
    elif tamper == "version":
        document.version_id = "f" * 32
    else:
        document.display_name = "Synthetic changed source name.txt"
    report, error = make_report(client, bench, matter, run, route)
    assert report is None and ("changed" in error or "identity" in error), error
    assert not bench.workspace.reports(matter.matter_id, ACTOR)


@pytest.mark.parametrize("route", ["direct", "guided"])
def test_long_reviewed_unit_refuses_report_without_slicing_or_losing_original_ledger(workspace, route):
    client, bench, matter = workspace
    run, documents = completed_text_run(bench, matter, ["The amber bicycle arrived. " * 300])
    decision = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, documents[0].document_id)
    assert decision.citations
    report, error = make_report(client, bench, matter, run, route)
    assert report is None and "6,000-character" in error and "original ledger" in error, error
    assert not bench.workspace.reports(matter.matter_id, ACTOR)
    ledger = client.get(f"/matters/{matter.slug}/full-review/{run.run_id}/text/export?format=json")
    assert ledger.status_code == 200
    assert len([row for row in ledger.json()["records"] if row["record_type"] == "range"]) == 2


def test_direct_summary_validates_uncited_source_omitted_by_fifty_detail_cap(workspace):
    client, bench, matter = workspace
    run, documents = completed_text_run(bench, matter, [f"Synthetic unrelated source {index}." for index in range(51)])
    ordered = tuple(bench.workspace.iter_review_decisions_for_report(matter.matter_id, ACTOR, run.run_id))
    assert len(ordered) == 51 and all(not item.citations for item in ordered)
    last = bench.source_store(matter).get(ordered[-1].document_id)
    path = bench.source_store(matter).derived / last.units_file
    value = json.loads(path.read_text())
    value["units"][0]["text"] += " Synthetic tampering beyond displayed decisions."
    path.write_text(json.dumps(value))
    report, error = make_report(client, bench, matter, run, "direct")
    assert report is None and "changed" in error
    assert not bench.workspace.reports(matter.matter_id, ACTOR)


@pytest.mark.parametrize('format_name', ['csv', 'json', 'markdown', 'docx'])
def test_full_text_source_check_exports_include_exact_passages(workspace, format_name):
    client, bench, matter = workspace
    text = 'The amber bicycle arrived. Synthetic exact support remains portable.'
    run, _ = completed_text_run(bench, matter, [text])
    response = client.get(f'/matters/{matter.slug}/full-review/{run.run_id}/export', params={'format': format_name})
    assert response.status_code == 200, response.text
    if format_name == 'json':
        assert response.json()['decisions'][0]['citations'][0]['excerpt'] == text
    elif format_name == 'docx':
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert text in archive.read('word/document.xml').decode()
    else:
        assert text in response.text


def test_complete_bundle_hydrates_full_text_source_check_citations(workspace):
    client, bench, matter = workspace
    text = 'The amber bicycle arrived. Synthetic bundle citation detail.'
    completed_text_run(bench, matter, [text])
    response = client.get(f'/matters/{matter.slug}/export')
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        paths = [name for name in archive.namelist() if 'source-checks/' in name and not name.endswith('full-text-ledger.json')]
        assert any(name.endswith('.csv') for name in paths)
        assert any(name.endswith('.json') for name in paths)
        assert all(text in archive.read(name).decode() for name in paths)


def test_corrupt_full_text_before_admission_never_reaches_classifier(workspace):
    from case_intelligence.generation import VerifiedReviewDecision
    client, bench, matter = workspace
    bench.full_review.close()
    store = bench.source_store(matter)
    document, _ = store.store_stream('synthetic-corrupt.txt', 'text/plain', io.BytesIO(b'Original synthetic text.'))
    path = store.derived / document.units_file
    payload = json.loads(path.read_text())
    payload['units'][0]['text'] = 'The amber bicycle was introduced by corruption.'
    path.write_text(json.dumps(payload))
    bench._sync_source_catalog(matter, [document])
    _, version = bench.workspace.create_review_criterion(matter.matter_id, ACTOR,
        title='Synthetic corruption refusal', instructions='Find the amber bicycle.')
    bench.workspace.queue_review_run(matter.matter_id, ACTOR, version.criterion_version_id,
        run_kind='full', review_mode='full_text')
    run = bench.workspace.claim_review_run('synthetic-corruption-worker')
    decision = bench.workspace.next_review_decision(run.run_id)
    calls = []
    bench.generator = type('SyntheticClassifier', (), {'classify_source': lambda self, **kw:
        calls.append(kw) or VerifiedReviewDecision('include', 'Synthetic support.', ('S1',), True, 1)})()
    outcome = bench._process_review_decision(run, decision, lambda: False)
    assert not calls
    assert outcome.decision == 'needs_attention' and not outcome.citations
    assert FullTextReviewLedger(bench.workspace).coverage(matter.matter_id, ACTOR, run.run_id)['sources'] == {'invalidated': 1}


def test_full_text_portable_export_keeps_a_long_cited_unit(workspace):
    client, bench, matter = workspace
    text = ('The amber bicycle arrived. ' + 'Synthetic surrounding context. ' * 250).rstrip()
    assert len(text) > 6000
    run, _ = completed_text_run(bench, matter, [text])
    response = client.get(f'/matters/{matter.slug}/full-review/{run.run_id}/export?format=json')
    assert response.status_code == 200, response.text
    assert response.json()['decisions'][0]['citations'][0]['excerpt'] == text
    decision = bench.workspace.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)[0]
    assert 'excerpt' not in decision.citations[0]


@pytest.mark.parametrize('failure', ['changed-text', 'changed-version', 'byte-limit'])
def test_full_text_portable_export_refuses_unresolved_or_oversized_support(workspace, monkeypatch, failure):
    from case_intelligence import work_product_exports
    client, bench, matter = workspace
    run, documents = completed_text_run(bench, matter, ['The amber bicycle arrived. Original exact source support.'])
    if failure == 'byte-limit':
        monkeypatch.setattr(work_product_exports, 'MAX_WORKFLOW_EXPORT_BYTES', 8)
    elif failure == 'changed-version':
        documents[0].version_id = 'f' * 32
    else:
        path = bench.source_store(matter).derived / documents[0].units_file
        value = json.loads(path.read_text()); value['units'][0]['text'] = 'Synthetic altered source.'; path.write_text(json.dumps(value))
    response = client.get(f'/matters/{matter.slug}/full-review/{run.run_id}/export?format=json')
    assert response.status_code == 409
    assert 'No partial export' in response.text
    assert bench._active_matter_response_count(matter.matter_id) == 0


@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.parametrize('view', ['inspector', 'recovery'])
def test_full_text_decision_inspector_resolves_exact_support_without_persisting_text(workspace, changed, view):
    client, bench, matter = workspace
    text = 'The amber bicycle arrived. Synthetic inspector support beyond the rationale.'
    run, documents = completed_text_run(bench, matter, [text])
    document = documents[0]
    saved = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, document.document_id)
    assert saved.citations and 'excerpt' not in saved.citations[0]
    if changed:
        path = bench.source_store(matter).derived / document.units_file
        payload = json.loads(path.read_text())
        payload['units'][0]['text'] = 'Synthetic changed inspector passage.'
        path.write_text(json.dumps(payload))
    if view == 'inspector':
        response = client.get(f'/matters/{matter.slug}/full-review', params={
            'criterion': run.criterion_id, 'run': run.run_id, 'source': document.document_id})
        assert response.status_code == 200
    else:
        response = client.post(f'/matters/{matter.slug}/full-review/{run.run_id}/decisions/{document.document_id}', data={
            'human_decision': 'invalid', 'note': 'Synthetic unsaved validation note.', 'expected_updated_at': saved.updated_at})
        assert response.status_code == 400
        assert 'Synthetic unsaved validation note.' in response.text
    if changed:
        assert 'Supporting passages are unavailable or changed' in response.text
        assert text not in response.text and 'Synthetic changed inspector passage.' not in response.text
        assert '<div class="decision-citations"><a' not in response.text
    else:
        assert f'<p>{text}</p>' in response.text
        assert 'Supporting passages are unavailable or changed' not in response.text
    retained = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, document.document_id)
    assert retained.citations == saved.citations and retained.updated_at == saved.updated_at
