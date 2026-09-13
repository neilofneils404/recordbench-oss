"""Synthetic multi-claim answer persistence keeps immutable support within its cap."""
import io
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from case_intelligence.managed_storage import StoragePolicy
from case_intelligence.workbench import create_workbench_app
from tests.test_guided_reports import finished, queue


def test_repeated_large_source_support_fits_saved_answer_and_report(tmp_path, monkeypatch):
    actor = "development-taylor-morgan"
    statements = [f"Pump Cedar synthetic observation {number} records the reference reading."
                  for number in range(1, 9)]
    raw = {"answerable": True, "claims": [
        {"text": statement, "evidence_ids": ["S1", "S2", "S3", "S4"]} for statement in statements],
        "limitation": None, "missing_information": ""}
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test",
        storage_policy=StoragePolicy(reserve_bytes=0),
        generator=SimpleNamespace(available=True, generate=lambda **kwargs: raw))
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.answers.close()
        bench.research.close()
        bench.full_review.close()
        matter = bench.create_matter("Synthetic answer size boundary", "", actor)
        store = bench.source_store(matter)
        documents, citations = [], []
        for number in range(1, 5):
            basis = " ".join(statements) + f" Synthetic copy {number}. "
            text = basis + "x" * (6000 - len(basis))
            document, _ = store.store_stream(f"Synthetic pressure note {number}.txt", "text/plain", io.BytesIO(text.encode()))
            unit = document.parsed_units()[0]
            assert unit.text == text and len(unit.text) == 6000
            documents.append(document)
            citations.append(bench._citation(matter, bench._candidate(matter, document, unit, 1)))
        bench._sync_source_catalog(matter, documents)
        monkeypatch.setattr(bench, "_answer_search", lambda *args, **kwargs: tuple(citations))
        conversation = bench.workspace.get_conversation(matter.matter_id)
        saved = bench.ask(matter, conversation, "What observations do the records describe?")
        assert len(saved.payload["claims"]) == 8 and not saved.payload["omitted_claims"]
        assert len(json.dumps(saved.payload, ensure_ascii=False, separators=(",", ":"))) < 100_000
        for claim in saved.payload["claims"]:
            assert len(claim["citations"]) == 4
            for original, reference in zip(citations, claim["citations"]):
                expected = bench._workflow_citation_payload(original)
                for key, value in expected.items():
                    if key != "excerpt":
                        assert reference[key] == value
                assert "excerpt" not in reference
        assert bench.workspace.messages(matter.matter_id, conversation.conversation_id)[-1] == saved
        result = finished(client, matter, queue(client, matter, [f"conversation:{conversation.conversation_id}"]))
        assert result["state"] == "succeeded", result
        report = bench.workspace.reports(matter.matter_id, actor)[0]
        references = [reference for section in bench.workspace.report_sections(matter.matter_id, report.report_id)
            for reference in bench.workspace.report_citations(matter.matter_id, report.report_id, section.section_id)]
        for original in citations:
            matching = [reference for reference in references if reference.support_token == original.support_token]
            assert matching
            assert all((reference.document_id, reference.source_version_id, reference.location, reference.excerpt)
                == (original.document_id, original.source_version_id, original.location, original.excerpt)
                for reference in matching)
