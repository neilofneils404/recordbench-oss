from __future__ import annotations

from dataclasses import replace
import io
import json
import sqlite3
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.report_review_basis import research_sections, review_sections
from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore

ACTOR = "development-taylor-morgan"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_INTELLIGENCE_STORAGE_RESERVE_GIB", "0")
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test")
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.research.close()
        response = client.post("/matters", data={"name": "Synthetic review basis"}, follow_redirects=False)
        matter = bench.matter(response.headers["location"].split("/")[2], ACTOR)
        yield client, bench, matter


def saved_research(bench, matter, *, answerable=True):
    document, _ = bench.source_store(matter).store_stream(
        "synthetic-arrival.txt", "text/plain", io.BytesIO(b"The blue bicycle arrived at noon.")
    )
    candidate = bench._candidate(matter, document, document.parsed_units()[0], 1)
    citation = bench._citation(matter, candidate)
    job, _ = bench.workspace.queue_research_job(
        matter.matter_id, ACTOR, "When did the bicycle arrive?", "Arrival investigation",
        "research-request-" + "c" * 32,
    )
    bench.workspace.claim_research_job("synthetic-report-worker")
    bench.workspace.set_research_plan(job.job_id, {"queries": ["bicycle arrival", "competing account"], "method": "Two recorded evidence searches."}, 4)
    answer = {"answerable": answerable, "claims": [
        {"text": candidate.text, "citations": [citation.staff_payload()]}
    ] if answerable else [], "missing_information": "The gate log was unavailable."}
    result = {
        "summary": candidate.text if answerable else "The gate log was unavailable.",
        "answer": answer,
        "evidence": [bench._workflow_citation_payload(citation)],
        "passes": [{"query": "bicycle arrival", "status": "supported" if answerable else "gap",
                    "text": candidate.text if answerable else "The gate log was unavailable.", "answer": answer},
                   {"query": "competing account", "status": "gap", "text": "No searchable passage matched this part of the research plan."}],
        "gaps": [{"query": "gate log", "note": "Missing log needs direct follow-up."}],
        "coverage": {"search_pass_count": 2, "candidate_passage_count": 4,
                     "evidence_passage_count": 1, "evidence_source_count": 1,
                     "searchable_count": 1, "total_count": 2, "excluded_count": 1,
                     "notice": "One source was excluded from these searches."},
    }
    job = bench.workspace.finish_research_job(job.job_id, result)
    return job, document


def convert(client, bench, matter, job):
    response = client.post(f"/matters/{matter.slug}/research/{job.job_id}/report", follow_redirects=False)
    assert response.status_code == 303
    assert "/reports?report=" in response.headers["location"], response.headers["location"]
    return bench.workspace.reports(matter.matter_id, ACTOR)[0]


def test_investigation_conversion_preserves_findings_gaps_coverage_and_method(workspace):
    client, bench, matter = workspace
    job, _ = saved_research(bench, matter)
    report = convert(client, bench, matter, job)
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    assert [section.heading for section in sections] == [
        "Review question", "Investigation findings", "Evidence pass 1", "Evidence pass 2",
        "Gaps and unresolved questions", "Scope and coverage", "Method and review basis",
    ]
    assert all(section.origin_id == job.job_id for section in sections)
    assert not bench.workspace.report_citations(matter.matter_id, report.report_id, sections[0].section_id)
    assert len(bench.workspace.report_citations(matter.matter_id, report.report_id, sections[1].section_id)) == 1
    assert not bench.workspace.report_citations(matter.matter_id, report.report_id, sections[3].section_id)
    text = "\n".join(section.body for section in sections)
    for value in ["Missing log needs direct follow-up", "One source was excluded", "Two recorded evidence searches", job.job_id, "may repeat"]:
        assert value in text


def test_abstention_does_not_become_verified_synthesis(workspace):
    client, bench, matter = workspace
    job, _ = saved_research(bench, matter, answerable=False)
    report = convert(client, bench, matter, job)
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    assert sections[1].heading == "Investigation outcome: needs review"
    assert "did not record an answerable" in sections[1].body
    assert all("Verified research synthesis" not in section.heading for section in sections)


def test_export_formats_bundle_and_edits_preserve_converted_basis(workspace):
    client, bench, matter = workspace
    job, _ = saved_research(bench, matter)
    report = convert(client, bench, matter, job)
    section = bench.workspace.report_sections(matter.matter_id, report.report_id)[4]
    bench.workspace.update_report_section(matter.matter_id, report.report_id, section.section_id, ACTOR,
        heading=section.heading, body=section.body + "\nReviewer will request the missing log.",
        expected_updated_at=section.updated_at, expected_status=report.status)
    marker = "Reviewer will request the missing log."
    for format_name in ("markdown", "docx"):
        response = client.get(f"/matters/{matter.slug}/reports/{report.report_id}/export?format={format_name}")
        assert response.status_code == 200
        if format_name == "markdown":
            text = response.content.decode()
        else:
            with zipfile.ZipFile(io.BytesIO(response.content)) as word:
                text = word.read("word/document.xml").decode()
        assert marker in text and "Scope and coverage" in text and job.job_id in text
    response = client.get(f"/matters/{matter.slug}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        inventory = json.loads(bundle.read("manifest.json"))["reports"][0]
        assert marker in bundle.read(inventory["markdown"]).decode()
        with zipfile.ZipFile(io.BytesIO(bundle.read(inventory["docx"]))) as word:
            assert marker in word.read("word/document.xml").decode()


def test_stale_support_or_malformed_late_section_creates_no_orphan_report(workspace):
    client, bench, matter = workspace
    job, document = saved_research(bench, matter)
    before = bench.workspace.reports(matter.matter_id, ACTOR)
    invalid = replace(job, result={**job.result, "gaps": [{"note": "x" * 50_001}]})
    with pytest.raises(WorkspaceProblem, match="too long"):
        bench.workspace.create_report_from_sections(matter.matter_id, ACTOR, "Invalid", "",
            origin_id=job.job_id, sections=research_sections(invalid))
    assert bench.workspace.reports(matter.matter_id, ACTOR) == before
    bench.source_store(matter).remove(document.document_id)
    response = client.post(f"/matters/{matter.slug}/research/{job.job_id}/report", follow_redirects=False)
    assert response.status_code == 303 and "error=" in response.headers["location"]
    assert bench.workspace.reports(matter.matter_id, ACTOR) == before


def test_converted_report_transaction_rolls_back_mid_insert_and_checks_membership(workspace):
    _client, bench, matter = workspace
    store = bench.workspace
    with store.connection:
        store.connection.execute("CREATE TEMP TRIGGER reject_second_section BEFORE INSERT ON workbench_report_section WHEN NEW.ordinal=2 BEGIN SELECT RAISE(ABORT, 'synthetic interrupted conversion'); END")
    sections = [{"heading": "First", "body": "One"}, {"heading": "Second", "body": "Two"}]
    with pytest.raises(sqlite3.IntegrityError):
        store.create_report_from_sections(matter.matter_id, ACTOR, "No orphan", "", origin_id="synthetic-run", sections=sections)
    assert store.reports(matter.matter_id, ACTOR) == ()
    assert store.connection.execute("SELECT count(*) FROM workbench_report_section").fetchone()[0] == 0
    with pytest.raises(KeyError):
        store.create_report_from_sections(matter.matter_id, "foreign-principal", "No access", "", origin_id="synthetic-run", sections=sections)


def test_converted_sections_survive_backup_and_clean_restore(workspace, tmp_path):
    _client, bench, matter = workspace
    report = bench.workspace.create_report_from_sections(matter.matter_id, ACTOR, "Portable basis", "",
        origin_id="synthetic-run", sections=[{"heading": "Coverage", "body": "One unavailable source remains."}])
    path = tmp_path / "restored.sqlite"
    with sqlite3.connect(path) as target:
        bench.workspace.connection.backup(target)
    restored = WorkspaceStore(path)
    try:
        assert restored.report_sections(matter.matter_id, report.report_id)[0].body == "One unavailable source remains."
        assert restored.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        restored.close()


def test_every_source_http_conversion_keeps_team_decision_and_original_support(workspace):
    client, bench, matter = workspace
    bench.full_review.close()
    _job, document = saved_research(bench, matter)
    bench.source_store(matter)
    criterion, version = bench.workspace.create_review_criterion(matter.matter_id, ACTOR,
        title="Synthetic inclusion", instructions="Include bicycle records.")
    run = bench.workspace.queue_review_run(matter.matter_id, ACTOR, version.criterion_version_id, run_kind="full")
    bench.workspace.claim_review_run("synthetic-check-worker")
    candidate = bench._candidate(matter, document, document.parsed_units()[0], 1)
    citation = bench._workflow_citation_payload(bench._citation(matter, candidate))
    bench.workspace.record_review_decision(run.run_id, document.document_id, decision="included",
        rationale="The source describes a bicycle.", citations=[citation])
    bench.workspace.finish_review_run(run.run_id)
    decision = bench.workspace.review_decision(matter.matter_id, ACTOR, run.run_id, document.document_id)
    bench.workspace.adjudicate_review_decision(matter.matter_id, ACTOR, run.run_id, document.document_id,
        human_decision="exclude", expected_updated_at=decision.updated_at,
        note="This is a conflicting account requiring follow-up.")
    response = client.post(f"/matters/{matter.slug}/full-review/{run.run_id}/report", follow_redirects=False)
    assert response.status_code == 303 and "/reports?report=" in response.headers["location"]
    report = bench.workspace.reports(matter.matter_id, ACTOR)[0]
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    text = "\n".join(item.body for item in sections)
    assert "Opposing machine/human inclusion labels: 1" in text
    assert "Human decision: exclude" in text and "Machine: included" in text
    assert "conflicting account requiring follow-up" in text
    assert bench.workspace.get_principal(ACTOR).display_name in text
    assert document.version_id in text
    for format_name in ("markdown", "docx"):
        response = client.get(f"/matters/{matter.slug}/reports/{report.report_id}/export?format={format_name}")
        assert response.status_code == 200, response.text


def test_machine_and_human_counts_disagreements_and_explicit_detail_caps():
    citation = {"document_id": "a" * 32, "source_version_id": "b" * 32, "support_token": "c" * 40,
                "source_name": "Synthetic source", "location": "Page 1", "excerpt": "Synthetic support."}
    decisions = [SimpleNamespace(ordinal=i, machine_decision="included", human_decision="",
        validation_sample=1, citations=tuple(citation.copy() for _ in range(3)),
        source_name=f"Synthetic source {i}", source_version_id="b" * 32, rationale="Machine rationale.",
        human_note="", reviewed_at=None, updated_at="2026-09-08T12:00:00Z", error_message="") for i in range(1, 62)]
    decisions[-1].human_decision = "exclude"
    decisions[-1].human_note = "Conflicting account needs review."
    decisions[-1].reviewed_at = "2026-09-08T12:01:00Z"
    run = SimpleNamespace(snapshot_count=61, run_id="synthetic-run", criterion_version_id="synthetic-criterion-v2", state="succeeded")
    sections = review_sections(run, decisions, criterion_title="Synthetic criterion", criterion_version=2,
        instructions="Include bicycle records.", ledger_path="/matters/synthetic/full-review?run=synthetic-run")
    assert "Opposing machine/human inclusion labels: 1" in sections[2]["body"]
    assert "No saved human review: 60" in sections[2]["body"]
    assert sections[3]["heading"] == "Decision detail 61"
    assert "Conflicting account needs review." in sections[3]["body"]
    assert sum(len(section["citations"]) for section in sections) == 100
    assert "50 of 61" in sections[-1]["body"] and "100 of 183" in sections[-1]["body"]
    assert "11 decision details are not reproduced" in sections[-1]["body"]
    assert "/matters/synthetic/full-review" in sections[-1]["body"]
    run.snapshot_count = 62
    with pytest.raises(WorkspaceProblem, match="complete frozen"):
        review_sections(run, decisions, criterion_title="Criterion", criterion_version=2,
            instructions="Rule", ledger_path="/matters/synthetic/full-review")
