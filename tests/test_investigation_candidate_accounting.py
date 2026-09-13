"""Producer-driven synthetic retrieval/neighbor accounting, not model quality."""
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace
import wave
import zipfile

import pytest
from fastapi.testclient import TestClient

from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.review_bench import RetrievalUnavailable
from case_intelligence.review_budget import ReviewBudget
from case_intelligence.workbench import create_workbench_app
from case_intelligence.work_product_exports import ExportProblem, validate_research_basis
from case_intelligence.workflow_jobs import WorkflowFailure
from case_intelligence.workspace_store import WorkspaceStore
from tests.test_matter_media_workflow import ImmediateMediaProcessor


QUESTION = (
    "Compare supported agreements, conflicts, and unresolved questions across "
    "the documents and recording about Pump Cedar."
)
DOCUMENTS = {
    "Inspection note.txt": (
        "During a training exercise, Pump Cedar showed an 18 psi reading while "
        "a reference gauge showed 12 psi. The operator paused the exercise. "
        "The reason for the difference was not yet established."
    ),
    "Maintenance entry.txt": (
        "A technician replaced Pump Cedar's sensor after the exercise. The entry "
        "does not record a follow-up comparison against the reference gauge."
    ),
    "Calibration comparison.txt": (
        "The exercise display exceeded the reference gauge by 6 psi. "
        "The maintenance entry lacks a documented verification measurement."
    ),
    "Break-room inventory.txt": "The inventory lists four cups and two chairs.",
}
TRANSCRIPT = (
    "I saw the operator stop the exercise after comparing two readings.",
    "I did not watch the sensor replacement",
    "or any later measurement.",
)


class CedarGenerator:
    """Return a close, independently supported sentence per selected passage."""

    available = True

    def generate(self, **kwargs):
        claims = []
        for source in kwargs["evidence"][:8]:
            text = source.excerpt.split(". ", 1)[0]
            if source.evidence_kind == "transcript":
                text = "The machine transcript appears to say that " + text
            claims.append({"text": text, "evidence_ids": [source.evidence_id]})
        return {"answerable": bool(claims), "claims": claims,
                "limitation": None, "missing_information": ""}


class CedarMediaProcessor(ImmediateMediaProcessor):
    """Controlled transcription transport; the generated WAV does not test ASR."""

    def transcript(self, owner, external_job_id):
        value = super().transcript(owner, external_job_id)
        for index, (segment, text) in enumerate(zip(value["segments"], TRANSCRIPT)):
            segment.update(text=text, model_text=text, start=index * 4.0,
                           end=(index + 1) * 4.0, overlap=False,
                           speaker={"cluster_id": "SPEAKER_00", "display_name": "SPEAKER_00",
                                    "identity_state": "cluster"})
        return value


@pytest.fixture
def cedar(tmp_path, monkeypatch):
    # The supported Linux gate provides /usr/bin media tools. For local developer
    # runs, inspect these same WAV bytes with the installed executable instead.
    if not Path("/usr/bin/ffprobe").is_file():
        from case_intelligence import media_preflight, pilot_uploads
        executables = {f"/usr/bin/{name}": shutil.which(name) for name in ("ffprobe", "ffmpeg")}
        assert all(executables.values()), "Install media tools to inspect the generated fixture"
        def command_for(command):
            return [executables.get(command[0], command[0]), *command[1:]]
        def run(command, *args, **kwargs):
            return subprocess.run(command_for(command), *args, **kwargs)
        def popen(command, *args, **kwargs):
            return subprocess.Popen(command_for(command), *args, **kwargs)
        shim = SimpleNamespace(**{**vars(subprocess), "run": run, "Popen": popen})
        monkeypatch.setattr(pilot_uploads, "subprocess", shim)
        monkeypatch.setattr(media_preflight, "subprocess", shim)
    app = create_workbench_app(
        tmp_path / "runtime", generator=CedarGenerator(), auth_mode="test",
        storage_policy=StoragePolicy(reserve_bytes=0),
        media_processor=CedarMediaProcessor(), media_poll_seconds=0.01,
    )
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.research.close()
        bench.research = None
        response = client.post("/matters", data={"name": "Synthetic Pump Cedar"},
                               follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        matter = bench.workspace.get_active_matter(slug)
        for name, text in DOCUMENTS.items():
            source = tmp_path / name
            source.write_text(text)
            response = client.post(f"/matters/{slug}/uploads", files=[
                ("files", (name, source.read_bytes(), "text/plain"))], follow_redirects=False)
            assert response.status_code == 303
        audio = tmp_path / "Staff recollection recording.wav"
        with wave.open(str(audio), "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(8_000)
            recording.writeframes(b"\0\0" * 8_000 * 12)
        assert client.post(f"/matters/{slug}/uploads", files=[
            ("files", (audio.name, audio.read_bytes(), "audio/wav"))],
            follow_redirects=False).status_code == 303
        store = bench.source_store(matter)
        deadline = time.monotonic() + 10
        continued = False
        while time.monotonic() < deadline:
            documents = {item.display_name: item for item in store.documents.values()}
            media = documents[audio.name]
            readiness = bench.workspace.matter_readiness(matter.matter_id)
            # Transcript projection precedes the durable media completion. The
            # real matter gate must be open before manually starting research.
            if (len(documents) == len(DOCUMENTS) + 1
                    and all(document.state == "ready" for document in documents.values())
                    and readiness.can_query
                    and readiness.searchable_count == len(documents)):
                break
            media_job = bench.workspace.media_job(matter.matter_id, media.document_id, media.version_id)
            if (media.state == "needs_review" and media_job
                    and media_job.state == "cancelled" and not continued):
                # The waveform is silence, so explicitly authorize the controlled
                # transcript fixture through the ordinary recording-check action.
                response = client.post(
                    f"/matters/{slug}/sources/{store.action_token(media)}/recording-check",
                    data={"action": "continue", "inspection_id": media_job.preflight["inspection_id"]},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                continued = True
            time.sleep(0.01)
        assert (len(documents) == len(DOCUMENTS) + 1
                and all(document.state == "ready" for document in documents.values())
                and readiness.can_query and readiness.searchable_count == len(documents)), (
            [(document.display_name, document.state, document.message) for document in documents.values()],
            readiness,
        )
        citations = {
            name: tuple(bench._citation(matter, bench._candidate(matter, document, unit, index))
                        for index, unit in enumerate(document.parsed_units(), 1))
            for name, document in documents.items()
        }
        assert len(citations[audio.name]) == 3
        controls = {"followup": "duplicate", "calls": [], "primary_transcript": False}
        primary = (citations["Inspection note.txt"][0], citations["Maintenance entry.txt"][0])
        anchor = citations[audio.name][1]

        def search(matter_arg, query, **kwargs):
            assert matter_arg.matter_id == matter.matter_id
            scope = kwargs.get("document_ids")
            controls["calls"].append((query, scope))
            if query != QUESTION:
                if controls["followup"] == "unavailable":
                    raise RetrievalUnavailable("Synthetic retrieval outage")
                if controls["followup"] == "empty":
                    return ()
            # Real answer retrieval must deduplicate both primary and scoped
            # results before real evidence selection adds the two neighbors.
            if scope is None:
                if controls["primary_transcript"]:
                    return (*primary, *citations[audio.name][:2], primary[0])
                return (*primary, primary[0])
            assert scope == frozenset({media.document_id})
            return (anchor, anchor)

        monkeypatch.setattr(bench, "search", search)
        job, _ = bench.workspace.queue_research_job(
            matter.matter_id, matter.owner_id, QUESTION, "Synthetic cross-source comparison",
            "research-request-" + "d" * 32,
        )
        yield bench, client, matter, job, citations, controls, media


def _run(cedar, *, unique_evidence=72):
    bench, _, _, job, *_ = cedar
    bench.workspace.claim_research_job("synthetic-accounting-worker")
    plan = bench._research_plan(job.question, job.title)
    plan["budget"] = ReviewBudget(unique_evidence=unique_evidence).metadata()
    claimed = bench.workspace.set_research_plan(job.job_id, plan, 7)
    result = bench._process_research_job(claimed, lambda: False)
    return claimed, result


def test_fixture_waits_for_committed_media_job_before_research(request, monkeypatch):
    projected = threading.Event()
    release = threading.Event()
    observed = []
    delete = CedarMediaProcessor.delete
    matter_readiness = WorkspaceStore.matter_readiness

    def hold_after_projection(processor, *args, **kwargs):
        delete(processor, *args, **kwargs)
        projected.set()
        assert release.wait(10), "Fixture never observed the pending media commit"

    def readiness_before_commit(workspace, matter_id):
        readiness = matter_readiness(workspace, matter_id)
        if projected.is_set() and not release.is_set():
            observed.append(readiness)
            release.set()
        return readiness

    monkeypatch.setattr(CedarMediaProcessor, "delete", hold_after_projection)
    monkeypatch.setattr(WorkspaceStore, "matter_readiness", readiness_before_commit)
    try:
        fixture = request.getfixturevalue("cedar")
        bench, _, _, _, *_ = fixture
        claimed, result = _run(fixture)
        assert bench._finish_research_job(claimed, result).state == "succeeded"
        assert projected.is_set() and len(observed) == 1
        assert observed[0].transcribing_count == 1 and not observed[0].can_query
    finally:
        release.set()


def test_primary_supplemental_and_neighbor_candidates_finish_with_exact_counts(cedar):
    bench, client, matter, job, citations, controls, media = cedar
    claimed, result = _run(cedar)
    # Baseline fails here: the actual producer records 3 hits but selects 5.
    saved = bench._finish_research_job(claimed, result)
    assert saved.state == "succeeded"
    first, duplicate = result["passes"]
    assert first["candidate_passages"] == first["hit_count"] == 5
    assert first["candidate_sources"] == 3
    assert first["selected_passages"] == first["new_evidence"] == first["analyzed_units"] == 5
    assert duplicate["hit_count"] == 3
    assert duplicate["selected_passages"] == duplicate["new_evidence"] == duplicate["analyzed_units"] == 0
    assert duplicate["retrieval_outcome"] == "no_new_evidence"
    assert result["candidate_count"] == result["lifetime_candidate_count"] == 8
    assert result["coverage"]["candidate_passage_count"] == 8
    assert result["budget"]["counts"]["candidate_occurrences"] == 8
    assert result["budget"]["counts"]["analyzed_unit_occurrences"] == 5
    assert len(result["evidence"]) == 5
    assert len(controls["calls"]) == 4  # Primary and modality retrieval on each pass.
    for source in result["evidence"]:
        current = bench._current_workflow_citation(matter, bench._workflow_citation(source))
        assert current is not None and current.excerpt == source["excerpt"]
        opened = client.get(source["href"])
        assert opened.status_code == 200 and source["source_name"] in opened.text
    status = client.get(f"/matters/{matter.slug}/research/{job.job_id}/status").json()
    assert status["state"] == "succeeded"
    assert status["review_budget"] == saved.review_budget
    page = client.get(f"/matters/{matter.slug}/research?job={job.job_id}")
    assert "5 candidate passages" in page.text
    portable = json.loads(bench.export_research_work_product(matter, saved, "json").body)["investigation"]
    assert portable["findings"][0]["hit_count"] == 5
    assert portable["coverage"]["passages_considered"] == 8
    for format_name in ("markdown", "docx"):
        exported = bench.export_research_work_product(matter, saved, format_name).body
        if format_name == "docx":
            with zipfile.ZipFile(io.BytesIO(exported)) as word:
                text = word.read("word/document.xml").decode()
        else:
            text = exported.decode()
        assert "Pump Cedar" in text and "Staff recollection recording.wav" in text
        assert media.version_id in text
    converted = client.post(f"/matters/{matter.slug}/research/{job.job_id}/report", follow_redirects=False)
    assert converted.status_code == 303 and "/reports?report=" in converted.headers["location"]
    report = bench.workspace.reports(matter.matter_id, matter.owner_id)[0]
    sections = bench.workspace.report_sections(matter.matter_id, report.report_id)
    support = [citation for section in sections for citation in bench.workspace.report_citations(
        matter.matter_id, report.report_id, section.section_id)]
    assert {item.source_name for item in support} >= {
        "Inspection note.txt", "Maintenance entry.txt", "Staff recollection recording.wav",
    }
    assert {item.kind for item in support} == {"source", "transcript"}
    by_token = {source["support_token"]: source for source in saved.result["evidence"]}
    for citation in support:
        assert citation.source_version_id == by_token[citation.support_token]["source_version_id"]
        assert citation.excerpt == by_token[citation.support_token]["excerpt"]
    for format_name in ("markdown", "docx"):
        exported = client.get(f"/matters/{matter.slug}/reports/{report.report_id}/export?format={format_name}")
        assert exported.status_code == 200
        if format_name == "docx":
            with zipfile.ZipFile(io.BytesIO(exported.content)) as word:
                text = word.read("word/document.xml").decode()
        else:
            text = exported.content.decode()
        assert "Pump Cedar" in text and "Staff recollection recording.wav" in text


def test_neighbor_already_returned_as_an_anchor_is_not_counted_twice(cedar):
    bench, _, _, _, _, controls, _ = cedar
    controls["primary_transcript"] = True
    claimed, result = _run(cedar)
    saved = bench._finish_research_job(claimed, result)
    first, duplicate = saved.result["passes"]
    assert first["hit_count"] == first["candidate_passages"] == first["selected_passages"] == 5
    assert duplicate["hit_count"] == 4 and duplicate["selected_passages"] == 0
    assert saved.result["candidate_count"] == 9
    assert len(controls["calls"]) == 2  # No missing-kind retrieval is needed.


@pytest.mark.parametrize("outcome", ["empty", "unavailable"])
def test_empty_and_unavailable_followups_preserve_honest_counts(cedar, outcome):
    bench, _, _, _, _, controls, _ = cedar
    controls["followup"] = outcome
    claimed, result = _run(cedar)
    saved = bench._finish_research_job(claimed, result)
    row = saved.result["passes"][1]
    assert row["candidate_passages"] == row["candidate_sources"] == 0
    assert row["selected_passages"] == row["new_evidence"] == row["analyzed_units"] == 0
    assert row["hit_count"] == (None if outcome == "unavailable" else 0)
    assert row["retrieval_outcome"] == ("unavailable" if outcome == "unavailable" else "zero_hits")
    assert saved.result["candidate_count"] == 5


def test_evidence_budget_counts_candidates_even_when_not_all_are_admitted(cedar):
    bench, _, _, _, *_ = cedar
    claimed, result = _run(cedar, unique_evidence=2)
    saved = bench._finish_research_job(claimed, result)
    row = saved.result["passes"][0]
    assert row["hit_count"] == row["candidate_passages"] == 5
    assert row["selected_passages"] == row["new_evidence"] == row["analyzed_units"] == 2
    assert saved.result["stop_reason"] == "evidence_budget"


def test_resume_keeps_committed_candidate_population_and_exact_sources(cedar):
    bench, _, matter, job, _, controls, _ = cedar
    claimed = bench.workspace.claim_research_job("synthetic-accounting-worker")
    with pytest.raises(WorkflowFailure, match="cancelled"):
        bench._process_research_job(claimed, lambda: len(controls["calls"]) >= 2)
    before = bench.workspace.research_job(matter.matter_id, matter.owner_id, job.job_id)
    assert before.result["candidate_count"] == 5
    assert before.result["passes"][0]["selected_passages"] == 5
    bench.workspace.fail_research_job(job.job_id, "Synthetic interruption after a committed pass")
    bench.workspace.retry_research_job(matter.matter_id, matter.owner_id, job.job_id)
    resumed = bench.workspace.claim_research_job("synthetic-accounting-resume")
    result = bench._process_research_job(resumed, lambda: False)
    saved = bench._finish_research_job(resumed, result)
    assert saved.result["passes"][0] == before.result["passes"][0]
    assert saved.result["candidate_count"] == 8
    assert sum(query == QUESTION for query, _ in controls["calls"]) == 2


def test_legacy_neighbor_accounting_is_not_silently_rewritten_on_resume(cedar, monkeypatch):
    bench, _, matter, job, _, controls, _ = cedar
    select = bench._answer_evidence_citations

    def legacy_selection(*args, **kwargs):
        # Recreate the old producer boundary, not fabricated result counters:
        # select real neighboring passages without reporting their candidates.
        kwargs.pop("candidate_callback", None)
        return select(*args, **kwargs)

    monkeypatch.setattr(bench, "_answer_evidence_citations", legacy_selection)
    claimed, result = _run(cedar)
    assert result["passes"][0]["hit_count"] == 3
    assert result["passes"][0]["selected_passages"] == 5
    with pytest.raises(WorkflowFailure, match="checkpoint could not be verified"):
        bench._finish_research_job(claimed, result)
    bench.workspace.fail_research_job(job.job_id, "Synthetic legacy checkpoint verification failure")
    before = bench.workspace.research_job(matter.matter_id, matter.owner_id, job.job_id)
    calls_before = len(controls["calls"])
    monkeypatch.setattr(bench, "_answer_evidence_citations", select)
    bench.workspace.retry_research_job(matter.matter_id, matter.owner_id, job.job_id)
    resumed = bench.workspace.claim_research_job("synthetic-legacy-resume")
    result = bench._process_research_job(resumed, lambda: False)
    assert result["passes"] == before.result["passes"]
    assert result["evidence"] == before.result["evidence"]
    assert len(controls["calls"]) == calls_before
    with pytest.raises(WorkflowFailure, match="checkpoint could not be verified"):
        bench._finish_research_job(resumed, result)


def test_invalid_counters_and_reviewed_transcript_changes_remain_rejected(cedar):
    bench, client, matter, _, _, _, media = cedar
    claimed, result = _run(cedar)
    saved = bench._finish_research_job(claimed, result)
    corrupted = json.loads(json.dumps(saved.result))
    corrupted["passes"][0]["hit_count"] = corrupted["passes"][0]["candidate_passages"] = 3
    with pytest.raises(ExportProblem, match="search outcome counters"):
        validate_research_basis(matter, replace(saved, result=corrupted))
    segment = bench.workspace.transcript_segments(matter.matter_id, media.document_id, media.version_id)[0]
    token = bench.source_store(matter).action_token(media)
    changed = client.post(f"/matters/{matter.slug}/sources/{token}/segments/{segment.segment_id}",
        data={"expected_revision": segment.current_revision,
              "text": "I saw the operator pause the exercise after comparing two readings."},
        follow_redirects=False)
    assert changed.status_code == 303 and "error=" not in changed.headers["location"]
    with pytest.raises(ExportProblem):
        bench.export_research_work_product(matter, saved, "json")
    with pytest.raises(WorkflowFailure, match="source changed"):
        bench._finish_research_job(claimed, result)
    assert bench.workspace.research_job(matter.matter_id, matter.owner_id, saved.job_id) == saved
