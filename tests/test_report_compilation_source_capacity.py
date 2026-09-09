"""Synthetic source admission and completeness checks for Report compilation."""
import pytest

from case_intelligence.generation import (
    GroundedGenerationService, MAX_ANSWER_CLAIMS, VerifiedAnswer, VerifiedClaim,
)
from case_intelligence.report_compilation import CompilationBudget, CompilationProblem, compile_report
from tests.test_report_compilation import citation, material


@pytest.mark.parametrize("kind", ["timeline", "entities", "topic"])
@pytest.mark.parametrize("count", [8, 9, 12])
def test_source_batches_allow_a_finding_for_every_passage(kind, count):
    packets = []

    class SourceEcho:
        available = True

        def generate(self, *, evidence, **kwargs):
            packets.append(len(evidence))
            return {"answerable": True, "claims": [
                {"text": item.excerpt, "evidence_ids": [item.evidence_id]}
                for item in evidence[:MAX_ANSWER_CLAIMS]
            ], "limitation": None, "missing_information": ""}

    selected = tuple(material(index, citations=(citation(index, text=f"Synthetic delivery record {index} identifies a blue device."),))
                     for index in range(1, count + 1))
    draft = compile_report(kind, "blue device delivery", selected, GroundedGenerationService(SourceEcho()))
    assert max(packets) <= MAX_ANSWER_CLAIMS
    assert draft.coverage["analyzed_source_passages"] == count
    assert draft.coverage["uncompiled_material_ids"] == ()
    for item in selected:
        assert any(section["body"].startswith(item.citations[0]["excerpt"]) for section in draft.sections)


def test_source_batch_call_budget_preserves_the_unvisited_saved_finding():
    class AllSources:
        available = True

        def answer(self, question, evidence, **kwargs):
            claims = tuple(VerifiedClaim(item.excerpt, (item.evidence_id,)) for item in evidence[:MAX_ANSWER_CLAIMS])
            return VerifiedAnswer(True, "", claims, None, "", tuple(item.evidence_id for item in evidence[:MAX_ANSWER_CLAIMS]), True, 1)

    selected = tuple(material(index, text=f"Original synthetic saved finding {index}.") for index in range(1, 10))
    draft = compile_report("topic", "delivery", selected, AllSources(), budget=CompilationBudget(max_model_calls=1))
    assert draft.coverage["analyzed_source_passages"] == 8
    assert draft.coverage["incompletely_analyzed_material_ids"] == (selected[-1].material_id,)
    assert any(section["body"].startswith(selected[-1].text) for section in draft.sections)
    assert draft.coverage["stop_reason"] == "budget_reached"


@pytest.mark.parametrize("mode", ["saturated", "duplicate", "rejected", "invalid_id"])
def test_limited_source_output_preserves_unrepresented_saved_material(mode):
    class PartialSources:
        available = True

        def answer(self, question, evidence, **kwargs):
            claims = (tuple(VerifiedClaim(f"Synthetic delivery observation {index}.", ("S1",)) for index in range(8))
                      if mode == "saturated" else (VerifiedClaim("Synthetic delivery observation.", ("S1",)),))
            if mode == "invalid_id":
                claims += (VerifiedClaim("Synthetic unsupported statement.", ("S99",)),)
            return VerifiedAnswer(True, "", claims, None, "", ("S1",), True, 1,
                                  omitted_claims=int(mode == "rejected"), duplicate_claims=int(mode == "duplicate"))

    selected = (material(1), material(2, text="The second synthetic saved finding concerns approval."))
    draft = compile_report("topic", "delivery", selected, PartialSources())
    assert any(section["body"].startswith(selected[1].text) for section in draft.sections)
    assert selected[1].material_id in draft.coverage["incompletely_analyzed_material_ids"]
    assert selected[1].material_id not in draft.coverage["uncompiled_material_ids"]
    assert draft.coverage["stop_reason"] == "analysis_incomplete"


@pytest.mark.parametrize("kind", ["timeline", "entities", "topic"])
@pytest.mark.parametrize("origin,status", [("research", "verified"), ("human", "disputed")])
@pytest.mark.parametrize("excerpt", ["", " \t\n "])
def test_blank_citation_excerpts_are_rejected_before_compilation(kind, origin, status, excerpt):
    item = material(origin=origin, review_status=status, citations=(citation(text=excerpt),))
    with pytest.raises(CompilationProblem, match="nonblank source excerpt"):
        compile_report(kind, "delivery" if kind == "topic" else "", (item,))


def test_mixed_valid_and_blank_citations_are_not_silently_filtered():
    item = material(citations=(citation(), citation(2, text=" ")))
    with pytest.raises(CompilationProblem, match="nonblank source excerpt"):
        compile_report("timeline", materials=(item,))
