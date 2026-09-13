"""Pump Cedar boundary checks; controlled answers are never model-quality scores."""
from collections import Counter
from contextlib import nullcontext
from dataclasses import replace
import hashlib
import html
import io
import re
from types import SimpleNamespace

import pytest

from case_intelligence.generation import (EvidenceItem, GroundedGenerationService,
    UnavailableGenerator)
from case_intelligence import workflow_quality_gold
from case_intelligence.workflow_quality_gold import (CRITERION, FOLLOW_UP, UNSUPPORTED_QUESTION,
    classification_metrics, fingerprint, sources)


def pdf_bytes(pages):
    """Create a fresh searchable synthetic PDF with no inherited metadata."""
    import textwrap
    from pypdf import PdfWriter
    from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject)
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding")})
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        content = DecodedStreamObject()
        lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                 for line in textwrap.wrap(text, 82)]
        content.set_data(("BT /F1 11 Tf 40 740 Td 15 TL " +
            " ".join(f"({line}) Tj T*" for line in lines) + " ET").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_gold_rubric_and_uncertainty_accounting_are_independent_of_predictions():
    cases = sources()
    assert len(cases) == 30
    assert Counter(case.relevant for case in cases) == {True: 24, False: 6}
    assert len({case.case_id for case in cases}) == 30
    assert fingerprint() == "320926a4336789d175567ab597ee204a653662b9c2b7c8960651705e1bc80cfb"
    assert len(next(case.units for case in cases if case.case_id == "late_page-comparison")) == 15
    perfect = {case.case_id: "include" if case.relevant else "not_identified" for case in cases}
    assert classification_metrics(perfect)["recall"] == 1
    # Deliberate misses and missing output test scoring, not model performance.
    perfect["baseline-maintenance"] = "not_identified"
    perfect["baseline-inventory"] = "include"
    perfect.pop("baseline-recollection")
    result = classification_metrics(perfect)
    assert result["false_negative_ids"] == ["baseline-maintenance"]
    assert result["unresolved_relevant_ids"] == ["baseline-recollection"]
    assert result["recall"] == 22 / 24 and result["conditional_recall"] == 22 / 23
    assert result["precision"] == 22 / 23
    assert classification_metrics({})["precision"] is None
    with pytest.raises(ValueError):
        classification_metrics({"not-in-fixture": "include"})


@pytest.mark.parametrize("control", ["SUITE", "CRITERION", "FOLLOW_UP", "UNSUPPORTED_QUESTION"])
def test_gold_fingerprint_changes_with_each_evaluation_control(monkeypatch, control):
    original = fingerprint()
    monkeypatch.setattr(workflow_quality_gold, control,
                        getattr(workflow_quality_gold, control) + " Synthetic changed control.")
    assert fingerprint() != original


@pytest.mark.parametrize("dimension", tuple(workflow_quality_gold.USEFULNESS_RUBRIC))
def test_gold_fingerprint_changes_with_each_semantic_rubric_definition(monkeypatch, dimension):
    original = fingerprint()
    monkeypatch.setitem(workflow_quality_gold.USEFULNESS_RUBRIC, dimension,
                        workflow_quality_gold.USEFULNESS_RUBRIC[dimension] + " Require an additional supported distinction.")
    assert fingerprint() != original


@pytest.mark.parametrize("change", [
    {"units": ("Synthetic changed source content.",)},
    {"relevant": False},
    {"reason": "Synthetic changed gold-label justification."},
])
def test_gold_fingerprint_changes_with_source_content_and_gold_labels(monkeypatch, change):
    original = fingerprint()
    cases = sources()
    monkeypatch.setattr(workflow_quality_gold, "sources", lambda: (replace(cases[0], **change), *cases[1:]))
    assert fingerprint() != original


def test_gold_fingerprint_is_stable_for_identical_inputs_and_rubric_mapping_order(monkeypatch):
    original = fingerprint()
    cases = tuple(replace(case) for case in sources())
    monkeypatch.setattr(workflow_quality_gold, "sources", lambda: cases)
    monkeypatch.setattr(workflow_quality_gold, "USEFULNESS_RUBRIC",
                        dict(reversed(tuple(workflow_quality_gold.USEFULNESS_RUBRIC.items()))))
    assert fingerprint() == original == fingerprint()


@pytest.mark.parametrize("miss_maintenance", [False, True])
@pytest.mark.parametrize("source_format", ["text", "pdf"])
def test_real_extraction_packets_coverage_source_links_and_human_override(tmp_path, miss_maintenance, source_format):
    from fastapi.testclient import TestClient
    from case_intelligence.full_text_review import FullTextReviewLedger
    from case_intelligence.managed_storage import StoragePolicy
    from case_intelligence.workbench import create_workbench_app
    from case_intelligence.workspace_store import WorkspaceProblem
    actor = "development-taylor-morgan"
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(),
        auth_mode="test", storage_policy=StoragePolicy(reserve_bytes=0))
    with TestClient(app) as client:
        bench = app.state.workbench
        bench.full_review.close()
        bench.research.close()
        matter = bench.create_matter("Synthetic Pump Cedar review", "", actor)
        store = bench.source_store(matter)
        # Genuine file extraction, including a late fifteenth PDF page. The spoken
        # statement is a plain text source here; timestamped media is evaluated
        # separately and this test makes no audio/transcription claim.
        cases = tuple(case for case in sources() if case.challenge == "late_page")
        documents = {}
        expected_packets = {}
        for case in cases:
            if case.evidence_kind == "transcript" or source_format == "text":
                name, media, content = case.title + ".txt", "text/plain", "\n".join(case.units).encode()
                expected = [" ".join(case.units)]
            else:
                name, media, content = case.title + ".pdf", "application/pdf", pdf_bytes(case.units)
                expected = list(case.units)
            document, _ = store.store_stream(name, media, io.BytesIO(content))
            assert document.state == "ready"
            extracted = tuple(document.iter_parsed_units())
            assert [" ".join(unit.text.split()) for unit in extracted] == expected
            assert len(extracted) == len(expected)
            documents[case.case_id] = document
            expected_packets[name] = (case, expected)
        bench._sync_source_catalog(matter, list(documents.values()))
        _, version = bench.workspace.create_review_criterion(matter.matter_id, actor,
            title="Synthetic discrepancy", instructions=CRITERION)
        queued = bench.workspace.queue_review_run(matter.matter_id, actor, version.criterion_version_id,
            run_kind="full", review_mode="full_text")
        run = bench.workspace.claim_review_run("synthetic-cedar-worker")
        assert run.run_id == queued.run_id
        seen = []
        def classify(**kwargs):
            evidence = kwargs["evidence"][0]
            seen.append((evidence.source_name, " ".join(evidence.excerpt.split())))
            case = expected_packets[evidence.source_name][0]
            included = (case.relevant and evidence.excerpt.strip() != "Synthetic page intentionally contains no substantive observation."
                and not (miss_maintenance and case.case_id.endswith("-maintenance")))
            rationale = (case.units[-1] if source_format == "text" and case.case_id.endswith("-comparison")
                         else evidence.excerpt)
            return {"decision": "include" if included else "not_identified",
                "rationale": rationale if included else "No match identified in this packet.",
                "evidence_ids": ["S1"] if included else []}
        bench.generator = GroundedGenerationService(SimpleNamespace(available=True, classify_source=classify))
        while (decision := bench.workspace.next_review_decision(run.run_id)) is not None:
            outcome = bench._process_review_decision(run, decision, lambda: False)
            bench._record_review_decision(run, decision, outcome)
        finished = bench._finish_review_run(run)
        assert finished.state == "succeeded"
        assert Counter(seen) == Counter((name, text) for name, (_, texts) in expected_packets.items() for text in texts)
        ledger = FullTextReviewLedger(bench.workspace)
        coverage = ledger.coverage(matter.matter_id, actor, run.run_id)
        assert coverage["units"] == {"processed": 5 if source_format == "text" else 19}
        assert coverage["inventory_complete"] and not coverage["has_gaps"]
        assert "does not establish" in coverage["notice"]
        page = client.get(f"/matters/{matter.slug}/full-review/{run.run_id}/text")
        assert page.status_code == 200 and "Completion does not establish" in page.text
        decisions = bench.workspace.review_decisions_for_export(matter.matter_id, actor, run.run_id)
        by_document = {item.document_id: item for item in decisions}
        actual = {case.case_id: {"included": "include", "excluded": "not_identified"}[by_document[
            documents[case.case_id].document_id].machine_decision] for case in cases}
        metrics = classification_metrics(actual, cases)
        assert metrics["recall"] == (0.75 if miss_maintenance else 1)
        assert metrics["precision"] == 1
        for item in decisions:
            for citation in item.citations:
                response = client.get(citation["href"])
                assert response.status_code == 200
                assert citation["document_id"] == item.document_id
                assert citation["source_version_id"] == item.source_version_id
                document = next(document for document in documents.values() if document.document_id == item.document_id)
                unit = next(unit for unit in document.iter_parsed_units() if unit.number == citation["unit_number"])
                rendered = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", response.text)).split())
                assert " ".join(unit.text.split()) in rendered
        exported = client.get(f"/matters/{matter.slug}/full-review/{run.run_id}/text/export?format=json")
        assert exported.status_code == 200 and "Recognition of every relevant fact is not established" in exported.text
        maintenance = by_document[documents["late_page-maintenance"].document_id]
        machine = (maintenance.machine_decision, maintenance.rationale, maintenance.citations)
        reviewed = bench.workspace.adjudicate_review_decision(matter.matter_id, actor, run.run_id,
            maintenance.document_id, human_decision="include", note="Replacement is relevant; confirmation remains undocumented.",
            expected_updated_at=maintenance.updated_at)
        assert (reviewed.machine_decision, reviewed.rationale, reviewed.citations) == machine
        assert reviewed.human_decision == "include" and reviewed.reviewed_by == actor
        with pytest.raises(WorkspaceProblem, match="changed"):
            bench.workspace.adjudicate_review_decision(matter.matter_id, actor, run.run_id,
                maintenance.document_id, human_decision="exclude", note="Stale edit", expected_updated_at=maintenance.updated_at)
        assert bench.workspace.review_decision(matter.matter_id, actor, run.run_id, maintenance.document_id) == reviewed
        reviewed_export = client.get(f"/matters/{matter.slug}/full-review/{run.run_id}/text/export?format=json")
        assert reviewed_export.status_code == 200 and reviewed.human_note in reviewed_export.text
        assert reviewed.reviewed_by in reviewed_export.text


def test_supported_uncertainty_duplicates_and_unsupported_purchase_order_boundary():
    cases = [case for case in sources() if case.challenge == "baseline" and case.relevant]
    evidence = tuple(EvidenceItem(f"S{number}", case.title, "Synthetic source location",
        " ".join(case.units), case.evidence_kind) for number, case in enumerate(cases, 1))
    statement = cases[0].units[0].split(". ", 1)[0] + "."
    maintenance = cases[1].units[0]
    raw = {"answerable": True, "claims": [
        {"text": statement, "evidence_ids": ["S1"]},
        {"text": statement, "evidence_ids": ["S1"]},
        {"text": maintenance, "evidence_ids": ["S2"]},
        {"text": "Purchase order PO-9999 authorized the replacement.", "evidence_ids": ["S2"]},
    ], "limitation": None, "missing_information": ""}
    service = GroundedGenerationService(SimpleNamespace(available=True, generate=lambda **kwargs: raw))
    answer = service.answer(FOLLOW_UP, evidence)
    assert [claim.text for claim in answer.claims] == [statement, maintenance]
    assert answer.duplicate_claims == 1 and answer.omitted_claims == 1
    assert "omitted" in answer.verification_notice and "PO-9999" not in answer.text
    assert "does not record a follow-up comparison" in answer.text
    raw.update(answerable=False, claims=[], missing_information="The supplied sources do not identify a purchase order number.")
    abstention = service.answer(UNSUPPORTED_QUESTION, evidence,
        history=(("user", FOLLOW_UP), ("assistant", answer.text)))
    assert not abstention.answerable and not abstention.claims and not abstention.used_evidence_ids
    assert "PO-9999" not in abstention.text


def test_generated_pdf_library_extraction_retains_all_authored_pages():
    from pypdf import PdfReader
    case = next(case for case in sources() if case.case_id == "late_page-comparison")
    reader = PdfReader(io.BytesIO(pdf_bytes(case.units)), strict=True)
    assert [" ".join(page.extract_text().split()) for page in reader.pages] == list(case.units)
    # This library read does not qualify the native resource-limited child.
    assert len(reader.pages) == 15


@pytest.fixture
def cedar_discovery(tmp_path):
    from case_intelligence.entity_discovery import EntityDiscovery
    from case_intelligence.entity_service import EntityService
    from case_intelligence.full_text_review import FullTextReviewLedger
    from case_intelligence.pilot_uploads import PilotUnit
    from tests.test_research_and_full_review import _store, ACTOR
    texts = ["Object: Pump Cedar; inspection date 2026-09-01.",
        "Object: Pump Cedar; maintenance date 2026-09-01.",
        "Object: Pump Cedar; comparison date 2026-09-01.",
        "Object: Pump Cedar II; inspection date 2026-09-02.",
        "Object: Pump Cedar 2; inspection date 03/04/2026."]
    store, matter = _store(tmp_path, count=len(texts))
    _, version = store.create_review_criterion(matter.matter_id, ACTOR,
        title="Synthetic device mentions", instructions=CRITERION)
    store.queue_review_run(matter.matter_id, ACTOR, version.criterion_version_id,
        run_kind="full", review_mode="full_text")
    run = store.claim_review_run("synthetic-cedar-discovery")
    decisions = store.review_decisions_for_export(matter.matter_id, ACTOR, run.run_id)
    originals = {decision.document_id: (decision, text) for decision, text in zip(decisions, texts)}
    for decision, text in originals.values():
        FullTextReviewLedger(store).inventory(run, decision, [PilotUnit(1, text)], current_source=lambda: True)
    def load(unit):
        decision, text = originals[unit["document_id"]]
        return text, dict(document_id=decision.document_id, source_version_id=decision.source_version_id,
            source_name=decision.source_name, location="Unit 1", unit_number=1, chunk_id="chunk-1",
            excerpt_digest=hashlib.sha256(text.encode()).hexdigest(), excerpt=text,
            support_token=hashlib.sha1((decision.document_id + text).encode()).hexdigest())
    def validate(references):
        return frozenset(index for index, reference in enumerate(references)
            if all(reference[key] == value for key, value in load({"document_id": reference["document_id"]})[1].items()))
    service = EntityService(store.entity_repository(), source_guard=nullcontext, resolve_support=lambda token: None,
        load_note=store.notebook_item, load_references=store.notebook_references, validate_references=validate)
    discovery = EntityDiscovery(service, load_unit=load)
    yield store, matter, run, discovery, originals, ACTOR
    store.close()


def test_repeated_device_date_suggestions_keep_offsets_distinct_candidates_and_undo(cedar_discovery):
    store, matter, run, discovery, originals, ACTOR = cedar_discovery
    coverage = discovery.step(matter.matter_id, ACTOR, run.run_id)
    assert coverage["counts"] == {"pending": 0, "processed": 5, "failed": 0, "invalidated": 0}
    entities, count = discovery.service.list(matter.matter_id, ACTOR)
    assert count == 10  # 10 occurrences, six distinct labels; not ten adjudicated identities.
    assert Counter(item["display_name"] for item in entities) == {
        "Pump Cedar": 3, "Pump Cedar II": 1, "Pump Cedar 2": 1,
        "2026-09-01": 3, "2026-09-02": 1, "03/04/2026": 1}
    for entity in entities:
        detail = discovery.service.detail(matter.matter_id, ACTOR, entity["entity_id"])
        mention = detail[1][0]
        text = originals[mention["document_id"]][1]
        assert text[mention["start_offset"]:mention["end_offset"]] == entity["display_name"]
        assert mention["review_status"] == "suggested" and mention["available"]
    first, second, _ = [item for item in entities if item["display_name"] == "Pump Cedar"]
    candidates, _, _ = discovery.service.reconciliation_detail(matter.matter_id, ACTOR, first["entity_id"])
    assert any(item["entity_id"] == second["entity_id"] for item in candidates)
    operation = discovery.service.reconcile(matter.matter_id, ACTOR, first["entity_id"],
        expected_revision=1, target_id=second["entity_id"], target_revision=1, action="merge")
    assert len(discovery.service.detail(matter.matter_id, ACTOR, second["entity_id"])[1]) == 2
    discovery.service.undo(matter.matter_id, ACTOR, operation)
    assert len(discovery.service.detail(matter.matter_id, ACTOR, second["entity_id"])[1]) == 1
    assert len(discovery.service.detail(matter.matter_id, ACTOR, first["entity_id"])[1]) == 1
