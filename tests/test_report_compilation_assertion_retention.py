"""Saved assertions retain identity when generated findings reuse their source."""
from dataclasses import replace

import pytest

from case_intelligence.generation import VerifiedAnswer, VerifiedClaim
from case_intelligence.report_compilation import compile_report
from tests.test_report_compilation import citation, material


@pytest.mark.parametrize("kind", ["timeline", "entities", "topic"])
def test_distinct_saved_assertions_sharing_a_passage_survive_generated_finding(kind):
    passage = citation(text="Alex delivered the device. A second account disputes the delivery.")
    first = material(text="Alex delivered the device.", citations=(passage,))
    second = material(2, text="A second account disputes the delivery.", citations=(passage,))
    class FirstClaimService:
        available = True
        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim(first.text, (evidence[0].evidence_id,)),), None, "", (evidence[0].evidence_id,), True, 0)
    draft = compile_report(kind, topic="device delivery", materials=(first, second), generator=FirstClaimService())
    saved = [section for section in draft.sections if section.get("category", "").startswith("Saved findings")]
    assert len(saved) == 1
    assert saved[0]["material_ids"] == (second.material_id,)
    assert second.text in saved[0]["body"]
    assert "does not independently verify this assertion" in saved[0]["body"]
    assert saved[0]["citations"] == second.citations
    assert second.material_id not in draft.coverage["uncompiled_material_ids"]


def test_identical_text_with_distinct_citation_set_is_not_represented():
    one, two = citation(), citation(2, text="The second source gives independent support.")
    first = material(text="Delivery occurred.", citations=(one,))
    second = replace(first, material_id="synthetic-other", citations=(one, two))
    class Service:
        available = True
        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim(first.text, (evidence[0].evidence_id,)),), None, "", (evidence[0].evidence_id,), True, 0)
    draft = compile_report("timeline", materials=(first, second), generator=Service())
    retained = [section for section in draft.sections if section.get("material_ids") == (second.material_id,)]
    assert len(retained) == 1 and retained[0]["citations"] == second.citations
