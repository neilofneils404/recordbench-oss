"""Synthetic regressions for generated finding identity and citation order."""
import pytest

from case_intelligence.generation import VerifiedAnswer, VerifiedClaim
from case_intelligence.report_compilation import (
    CompilationBudget, CompilationMaterial, compile_report,
)


def materials():
    return tuple(CompilationMaterial(
        material_id=f"synthetic-record-{index}", origin="research", title="Synthetic finding",
        text="A synthetic delivery was recorded.", review_status="verified", revision="synthetic-revision-1",
        citations=({"kind": "source", "document_id": f"{index:032x}",
                    "source_version_id": f"{index + 100:032x}", "support_token": f"{index:040x}",
                    "source_name": f"Synthetic source {index}.txt", "location": "Line 1",
                    "excerpt": "A synthetic delivery was recorded and then reviewed."},),
    ) for index in (1, 2))


@pytest.mark.parametrize("first_order", [("S1", "S2"), ("S2", "S1")])
@pytest.mark.parametrize("kind,categories", [("timeline", ("Chronology",)),
                                              ("entities", ("People", "Places", "Things"))])
def test_reordered_support_deduplicates_without_losing_first_display_order(first_order, kind, categories):
    class ReorderedSupport:
        available = True

        def answer(self, question, evidence, **kwargs):
            claims = (
                VerifiedClaim("A synthetic delivery was recorded.", first_order),
                VerifiedClaim("A synthetic delivery was recorded.", tuple(reversed(first_order))),
                VerifiedClaim("A synthetic delivery was recorded.", (*first_order, first_order[0])),
                VerifiedClaim("The synthetic delivery was then reviewed.", first_order),
            )
            return VerifiedAnswer(True, "", claims, None, "", first_order, True, 1)

    selected = materials()
    draft = compile_report(kind, materials=selected, generator=ReorderedSupport(),
                           budget=CompilationBudget(max_sections=2 * len(categories)))
    expected_citations = tuple(selected[int(identifier[1:]) - 1].citations[0] for identifier in first_order)
    for category in categories:
        findings = [section for section in draft.sections if section.get("category") == category]
        assert len(findings) == 2
        assert findings[0]["body"].startswith("A synthetic delivery was recorded.")
        assert findings[1]["body"].startswith("The synthetic delivery was then reviewed.")
        assert all(section["citations"] == expected_citations for section in findings)
    # Generated duplicates consume no extra slots; the two distinct original
    # saved assertions are disclosed when the explicit section budget is full.
    assert draft.coverage["omitted_sections"] == len(selected)
    assert set(draft.coverage["uncompiled_material_ids"]) == {item.material_id for item in selected}


def test_same_text_with_different_support_sets_remains_distinct():
    class DistinctSupport:
        available = True

        def answer(self, question, evidence, **kwargs):
            claims = tuple(VerifiedClaim("A synthetic delivery was recorded.", (item.evidence_id,))
                           for item in evidence)
            return VerifiedAnswer(True, "", claims, None, "", ("S1", "S2"), True, 1)

    selected = materials()
    draft = compile_report("timeline", materials=selected, generator=DistinctSupport())
    findings = [section for section in draft.sections if section.get("category") == "Chronology"]
    assert len(findings) == 2
    assert tuple(section["citations"] for section in findings) == tuple(item.citations for item in selected)
