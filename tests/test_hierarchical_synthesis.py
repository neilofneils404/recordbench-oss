"""Synthetic provenance, >12-unit recall, interruption and budget acceptance."""
from copy import deepcopy
import hashlib

import pytest

from case_intelligence.generation import GroundedGenerationService
from case_intelligence.hierarchical_synthesis import (
    POLICY, run_synthesis, synthesis_answer, validate_state,
)


class SourceEcho:
    available = True

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"answerable": True, "claims": [
            {"text": source.excerpt, "evidence_ids": [source.evidence_id]}
            for source in kwargs["evidence"][:8]], "limitation": None, "missing_information": ""}


@pytest.fixture
def corpus():
    evidence, passes = [], []
    for index in range(24):
        text = (f"Synthetic dispatch record {index + 1} states the crate was delivered."
                if index != 23 else "Synthetic dispatch record 24 states the crate was not delivered.")
        token = hashlib.sha1(f"synthetic-{index}".encode()).hexdigest()
        evidence.append({"support_token": token, "source_name": f"synthetic-{index}.txt",
                         "location": "page 1", "excerpt": text, "evidence_kind": "document",
                         "document_id": f"synthetic-source-{index}", "source_version_id": "synthetic-v1"})
        passes.append({"answer": {"claims": [{"text": text, "citations": [{"support_token": token}]}]}})
    return passes, evidence


def execute(corpus, saved=None, checkpoint=lambda state: None, boundary=lambda: None, now=lambda: 1000):
    passes, evidence = corpus
    client = SourceEcho()
    state = run_synthesis("What do the dispatch records say about delivery?", passes, evidence,
                          GroundedGenerationService(client), checkpoint, boundary, saved, now=now)
    return state, client


def test_support_and_contradiction_across_24_units_keep_originals_through_both_levels(corpus):
    state, client = execute(corpus)
    validate_state(state, *corpus, final=True)
    answer = synthesis_answer(state, corpus[1])
    assert len(answer.claims) == 24
    assert any("was delivered" in claim.text for claim in answer.claims)
    assert any("was not delivered" in claim.text for claim in answer.claims)
    assert answer.claims[-1].evidence_ids == ("S24",)
    assert len(state["issue"]) == len(state["matter"]) == 6
    assert len({parent.split("C")[0] for parent in state["matter"][0]["parents"]}) > 1
    assert not state["partial"] and state["stop_reason"] == "completed"
    assert state["requests_spent"] == len(client.calls) == 12
    for call in client.calls:
        assert len(call["evidence"]) <= 12
        assert all(item.source_name.startswith("synthetic-") for item in call["evidence"])
        assert "derived_findings_not_evidence" in call["working_context"]


def test_interruption_reuses_nodes_but_does_not_refund_inflight_request(corpus):
    saved = []
    def checkpoint(state):
        saved.append(deepcopy(state))
        if state["requests_spent"] == 3 and len(state["issue"]) == 2:
            raise RuntimeError("Synthetic crash before response")
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        execute(corpus, checkpoint=checkpoint)
    resumed, client = execute(corpus, saved[-1])
    assert resumed["issue"][:2] == saved[-1]["issue"]
    assert resumed["requests_spent"] == 13
    assert len(client.calls) == 10
    completed, client = execute(corpus, resumed)
    assert not client.calls and completed == resumed


def test_unsupported_saved_finding_is_never_promoted(corpus):
    corpus[0][0]["answer"]["claims"][0]["text"] = "A submarine transported 9999 satellites to Jupiter."
    state, client = execute(corpus)
    assert state["rejected_findings"] == ["P1C1"] and state["partial"]
    assert "Jupiter" not in synthesis_answer(state, corpus[1]).text
    assert all("Jupiter" not in call["working_context"] for call in client.calls)


@pytest.mark.parametrize("mutation", ["text", "token", "parent", "partial", "omitted", "final"])
def test_corrupted_intermediate_or_completion_receipt_is_rejected(corpus, mutation):
    state, _ = execute(corpus)
    claim = state["issue"][0]["claims"][0]
    if mutation == "text":
        claim["text"] = "A submarine transported 9999 satellites to Jupiter."
    elif mutation == "token":
        claim["support_tokens"] = ["not-an-original"]
    elif mutation == "parent":
        claim["parents"] = ["invented-node"]
    elif mutation == "partial":
        state["partial"] = True
    elif mutation == "omitted":
        state["omitted_groups"] = ["invented"]
    else:
        state["matter"][0]["claims"][0]["text"] = "The crate was transported in 9999."
    with pytest.raises(ValueError):
        validate_state(state, *corpus, final=True)


def test_changed_source_invalidates_nodes_without_refunding_calls(corpus):
    state, _ = execute(corpus)
    corpus[1][0]["source_version_id"] = "synthetic-v2"
    with pytest.raises(ValueError, match="no longer matches"):
        validate_state(state, *corpus)
    rebuilt, client = execute(corpus, state)
    assert rebuilt["requests_spent"] == 24 and len(client.calls) == 12
    assert rebuilt["basis"] != state["basis"]


@pytest.mark.parametrize("reason", ["time_budget", "generation_budget"])
def test_budget_exhaustion_retains_explicit_partial_and_omitted_groups(corpus, reason):
    saved = []
    def checkpoint(state):
        saved.append(deepcopy(state))
        if state["requests_spent"] == 1:
            raise RuntimeError("Synthetic interruption")
    with pytest.raises(RuntimeError):
        execute(corpus, checkpoint=checkpoint)
    if reason == "generation_budget":
        saved[-1]["requests_spent"] = POLICY["generation_requests"]
    state, client = execute(corpus, saved[-1], now=lambda: 2000 if reason == "time_budget" else 1000)
    assert not client.calls and state["partial"]
    assert state["stop_reason"] == reason
    assert "matter_pending_issue_completion" in state["omitted_groups"]
    validate_state(state, *corpus, final=True)


def test_live_workflow_backup_clean_restore_and_exports(tmp_path):
    import json
    import sqlite3
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from case_intelligence.managed_storage import StoragePolicy
    from case_intelligence.workbench import create_workbench_app
    from case_intelligence.workspace_store import WorkspaceStore
    from case_intelligence.work_product_exports import ExportProblem, validate_research_basis

    app = create_workbench_app(tmp_path / "runtime", generator=SourceEcho(), auth_mode="test",
                               storage_policy=StoragePolicy(reserve_bytes=0))
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.research.close()
        bench.research = None
        response = client.post("/matters", data={"name": "Synthetic hierarchical acceptance"}, follow_redirects=False)
        matter = bench.workspace.get_active_matter(response.headers["location"].split("/")[2])
        citations = []
        for index in range(24):
            text = (f"Synthetic dispatch record {index + 1} states the crate was delivered."
                    if index != 23 else "Synthetic dispatch record 24 states the crate was not delivered.")
            name = f"synthetic-{index}.txt"
            assert client.post(f"/matters/{matter.slug}/uploads", files=[("files", (name, text.encode(), "text/plain"))]).status_code == 200
            citations.append(next(item for item in bench.search(matter, str(index + 1) + " dispatch", limit=20)
                                  if item.source_name == name))
        searches = []
        def search(matter_arg, question, query, **kwargs):
            searches.append(query)
            kwargs["retrieval_boundary"]["source_fingerprint"] = bench.workspace.source_availability_fingerprint(matter.matter_id)
            ordinal = int(query[-1])
            return tuple(citations[ordinal * 8:(ordinal + 1) * 8])
        bench._answer_search = search
        job, _ = bench.workspace.queue_research_job(matter.matter_id, matter.owner_id,
            "What do the dispatch records say about delivery?", "Synthetic hierarchy", "research-request-" + "c" * 32)
        claimed = bench.workspace.claim_research_job("synthetic-worker")
        claimed = bench.workspace.set_research_plan(job.job_id,
            {"queries": ["synthetic group 0", "synthetic group 1", "synthetic group 2"], "synthesis_version": 1}, 5)
        original_checkpoint = bench.workspace.checkpoint_research_job
        def checkpoint(job_id, result):
            saved = original_checkpoint(job_id, result)
            hierarchy = result.get("hierarchical_synthesis")
            if hierarchy and len(hierarchy["issue"]) == 2:
                raise RuntimeError("Synthetic interruption after saved issue groups")
            return saved
        bench.workspace.checkpoint_research_job = checkpoint
        with pytest.raises(RuntimeError, match="Synthetic interruption"):
            bench._process_research_job(claimed, lambda: False)
        bench.workspace.checkpoint_research_job = original_checkpoint
        destination = tmp_path / "clean-restore.sqlite"
        with sqlite3.connect(destination) as output:
            bench.workspace.connection.backup(output)
        restored = WorkspaceStore(destination)
        assert restored.recover_running_research_jobs() == 1
        assert restored.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not restored.connection.execute("PRAGMA foreign_key_check").fetchall()
        original_workspace = bench.workspace
        bench.workspace = restored
        try:
            resumed = restored.claim_research_job("synthetic-restored-worker")
            result = bench._process_research_job(resumed, lambda: False)
            completed = bench._finish_research_job(resumed, result)
            assert len(searches) == 3
            assert len(result["answer"]["claims"]) == 24
            assert "was not delivered" in result["summary"]
            assert completed.result["hierarchical_synthesis"]["requests_spent"] == 12
            for format_name in ("json", "markdown", "docx"):
                artifact = bench.export_research_work_product(matter, completed, format_name)
                assert artifact.body
                if format_name == "json":
                    exported = json.loads(artifact.body)["investigation"]
                    assert len(exported["hierarchical_synthesis"]["matter"]) == 6
                elif format_name == "markdown":
                    assert b"synthetic-23.txt" in artifact.body and b"matter6" in artifact.body
            corrupted = deepcopy(result)
            corrupted["hierarchical_synthesis"]["matter"][0]["claims"][0]["support_tokens"] = ["not-original"]
            with pytest.raises(ExportProblem, match="provenance"):
                validate_research_basis(matter, replace(completed, result=corrupted))
        finally:
            bench.workspace = original_workspace
            restored.close()


def test_unknown_checkpoint_version_cannot_be_reset_by_changed_inputs(corpus):
    state, _ = execute(corpus)
    state["version"] = 999
    corpus[1][0]["source_version_id"] = "synthetic-v2"
    with pytest.raises(ValueError, match="Unknown"):
        execute(corpus, state)


def test_model_invented_intermediate_statement_is_filtered_before_matter_context(corpus):
    class InventingClient(SourceEcho):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            raw["claims"].append({"text": "A submarine transported 9999 satellites to Jupiter.", "evidence_ids": ["S1"]})
            return raw
    client = InventingClient()
    state = run_synthesis("What do the dispatch records say about delivery?", *corpus,
                          GroundedGenerationService(client), lambda value: None, lambda: None)
    assert state["partial"]
    assert "Jupiter" not in synthesis_answer(state, corpus[1]).text
    assert all("Jupiter" not in call["working_context"] for call in client.calls)
    assert sum(node["omitted_claims"] for node in state["issue"]) > 0


def test_boundary_revocation_after_generation_prevents_saving_response(corpus):
    saved = []
    client = SourceEcho()
    def boundary():
        if client.calls:
            raise RuntimeError("Synthetic membership revoked")
    with pytest.raises(RuntimeError, match="membership revoked"):
        run_synthesis("What do the dispatch records say about delivery?", *corpus,
                      GroundedGenerationService(client), lambda value: saved.append(deepcopy(value)), boundary)
    assert saved[-1]["requests_spent"] == 1
    assert saved[-1]["issue"] == []
