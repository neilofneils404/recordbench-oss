"""Synthetic coverage for complete, capacity-safe review classification."""
import pytest

from case_intelligence.generation import (
    ANSWER_SCHEMA, GroundedGenerationService, MAX_EVIDENCE_ITEM_CHARS,
    VerifiedAnswer, VerifiedClaim,
)
from case_intelligence.report_compilation import CompilationBudget, compile_report
from tests.test_report_compilation import material


@pytest.mark.parametrize("count", [8, 9, 12])
@pytest.mark.parametrize("kind", ["topic", "timeline", "entities"])
def test_every_relevant_record_fits_classification_output_capacity(count, kind):
    packets = []
    claim_limit = ANSWER_SCHEMA["properties"]["claims"]["maxItems"]

    class SchemaLimitedClient:
        available = True

        def generate(self, *, evidence, **kwargs):
            packets.append(len(evidence))
            return {"answerable": True, "claims": [
                {"text": item.excerpt, "evidence_ids": [item.evidence_id]}
                for item in evidence[:claim_limit]
            ], "limitation": None, "missing_information": ""}

    notes = tuple(material(index, origin="human", review_status="disputed", citations=(),
                           text=f"Synthetic reviewer {index} disputes delivery of the blue device at Harbor Annex.")
                  for index in range(1, count + 1))
    draft = compile_report(kind, "blue device delivery", notes,
                           GroundedGenerationService(SchemaLimitedClient()))
    assert packets and max(packets) <= claim_limit
    assert draft.coverage["classified_review_records"] == count
    assert draft.coverage["omitted_human_material_ids"] == ()
    for note in notes:
        assert any(section["body"].startswith(note.text) for section in draft.sections)


@pytest.mark.parametrize("kind", ["topic", "timeline", "entities"])
def test_relevance_after_truncated_prefix_is_retained_as_unchecked(kind):
    class PrefixClassifier:
        available = True

        def answer(self, question, evidence, **kwargs):
            assert all("delivery" not in item.excerpt for item in evidence)
            return VerifiedAnswer(False, "", (), None, "No related content in this prefix.", (), True, 1)

    prefix = "Synthetic unrelated administrative text. ".ljust(MAX_EVIDENCE_ITEM_CHARS, "x")
    note = material(origin="human", review_status="disputed", citations=(),
                    text=prefix + " The synthetic delivery date is disputed.")
    draft = compile_report(kind, "delivery", (note,), PrefixClassifier())
    assert draft.sections[0]["body"].startswith(note.text)
    assert "relevance has not been fully checked" in draft.sections[0]["compilation_basis"]
    assert draft.coverage["classified_review_records"] == 0
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["retained_unclassified_review_material_ids"] == (note.material_id,)
    assert draft.coverage["truncated_review_material_ids"] == (note.material_id,)
    assert draft.coverage["classification_truncated_chars"] == len(note.text) - MAX_EVIDENCE_ITEM_CHARS
    assert draft.coverage["stop_reason"] == "analysis_incomplete"


def test_complete_note_at_prefix_boundary_can_still_be_excluded():
    class NoRelatedContent:
        available = True

        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),), None, "", ("S1",), True, 1)

    related = material(1, origin="human", citations=(), text="Synthetic delivery review.")
    unrelated = material(2, origin="human", citations=(), text="Synthetic unrelated administrative text. ".ljust(MAX_EVIDENCE_ITEM_CHARS, "x"))
    draft = compile_report("topic", "delivery", (related, unrelated), NoRelatedContent())
    assert draft.coverage["classified_review_records"] == 2
    assert draft.coverage["omitted_human_material_ids"] == (unrelated.material_id,)
    assert draft.coverage["truncated_review_material_ids"] == ()


def test_smaller_classification_batches_keep_later_notes_when_call_budget_ends():
    claim_limit = ANSWER_SCHEMA["properties"]["claims"]["maxItems"]

    class AllRelated:
        available = True

        def answer(self, question, evidence, **kwargs):
            claims = tuple(VerifiedClaim(item.excerpt, (item.evidence_id,)) for item in evidence[:claim_limit])
            return VerifiedAnswer(True, "", claims, None, "", tuple(item.evidence_id for item in evidence[:claim_limit]), True, 1)

    notes = tuple(material(index, origin="human", citations=()) for index in range(1, 13))
    draft = compile_report("topic", "delivery", notes, AllRelated(), budget=CompilationBudget(max_model_calls=1))
    assert draft.coverage["classified_review_records"] == claim_limit
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["retained_unclassified_review_material_ids"] == tuple(note.material_id for note in notes[claim_limit:])
    assert all(any(section["body"].startswith(note.text) and section["material_ids"] == (note.material_id,)
                   for section in draft.sections) for note in notes)


def test_rejected_classification_claim_cannot_prove_another_record_irrelevant():
    class PartlyVerifiedClassifier:
        available = True

        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),),
                                  None, "", ("S1",), True, 1, omitted_claims=1)

    notes = tuple(material(index, origin="human", citations=(),
                           text=f"Synthetic delivery disagreement {index}.") for index in (1, 2))
    draft = compile_report("topic", "delivery", notes, PartlyVerifiedClassifier())
    assert draft.coverage["classified_review_records"] == 0
    assert draft.coverage["omitted_human_material_ids"] == ()
    for note in notes:
        assert any(section["body"].startswith(note.text) for section in draft.sections)


@pytest.mark.parametrize("exact_duplicate", [False, True])
def test_repeated_record_claim_cannot_exhaust_capacity_and_exclude_another_note(exact_duplicate):
    class RepeatedRecordClient:
        available = True

        def generate(self, *, evidence, **kwargs):
            claims = [{"text": item.excerpt, "evidence_ids": [item.evidence_id]} for item in evidence[:7]]
            repeated_text = evidence[0].excerpt if exact_duplicate else evidence[0].excerpt + " " + evidence[0].excerpt
            claims.append({"text": repeated_text, "evidence_ids": ["S1"]})
            return {"answerable": True, "claims": claims, "limitation": None, "missing_information": ""}

    notes = tuple(material(index, origin="human", citations=(),
                           text=f"Synthetic reviewer {index} disputes the blue device delivery.") for index in range(1, 9))
    draft = compile_report("topic", "blue device delivery", notes, GroundedGenerationService(RepeatedRecordClient()))
    assert draft.coverage["classified_review_records"] == 0
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert any(section["body"].startswith(notes[-1].text) for section in draft.sections)
