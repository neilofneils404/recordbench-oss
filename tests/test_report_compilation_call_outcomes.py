"""Synthetic coverage for unavailable and rejected answer-service calls."""
import pytest

from case_intelligence.generation import (
    GenerationGroundingRejected, GenerationRejected, GenerationUnavailable, GroundedGenerationService,
)
from case_intelligence.report_compilation import compile_report
from tests.test_report_compilation import material


@pytest.mark.parametrize("stage", ["classification", "source"])
@pytest.mark.parametrize("error", [GenerationUnavailable, GenerationRejected, GenerationGroundingRejected])
def test_failed_answer_calls_keep_distinct_coverage_outcomes(stage, error):
    class FailedService:
        available = True

        def answer(self, *args, **kwargs):
            raise error("Synthetic service failure")

    item = material(origin="human", citations=()) if stage == "classification" else material()
    draft = compile_report("topic", "delivery", (item,), FailedService())
    rejected = int(issubclass(error, GenerationRejected))
    assert draft.coverage["model_calls"] == 1
    assert draft.coverage["classification_calls"] == int(stage == "classification")
    assert draft.coverage["rejected_model_calls"] == rejected
    assert draft.coverage["unavailable_model_calls"] == 1 - rejected
    assert draft.coverage["rejected_claims"] == 0
    assert draft.coverage["stop_reason"] == "analysis_incomplete"
    assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"
    assert any(section["body"].startswith(item.text) for section in draft.sections)
    ledger = draft.sections[-1]["body"]
    assert f"unavailable model calls: {1 - rejected}" in ledger
    assert f"rejected answer-service calls: {rejected}" in ledger
    if rejected:
        assert "AI assistance was unavailable" not in ledger
        assert "did not produce an accepted answer" in ledger
    else:
        assert "AI assistance was unavailable" in ledger


@pytest.mark.parametrize("mode", ["invalid_structure", "ungrounded"])
def test_real_service_rejection_is_not_reported_as_an_outage(mode):
    class RejectedClient:
        available = True

        def generate(self, **kwargs):
            if mode == "invalid_structure":
                return {"unexpected": "Synthetic invalid response"}
            return {"answerable": True, "claims": [{"text": "An unsupported helicopter arrived at 99:99.",
                    "evidence_ids": ["S1"]}], "limitation": None, "missing_information": ""}

    item = material()
    draft = compile_report("topic", "delivery", (item,), GroundedGenerationService(RejectedClient()))
    assert draft.coverage["rejected_model_calls"] == 1
    assert draft.coverage["unavailable_model_calls"] == 0
    assert draft.sections[0]["body"].startswith(item.text)


@pytest.mark.parametrize("classification_error,source_error", [
    (GenerationRejected, GenerationUnavailable), (GenerationUnavailable, GenerationRejected),
])
def test_mixed_failed_call_types_preserve_both_counters(classification_error, source_error):
    class MixedService:
        available = True
        calls = 0

        def answer(self, *args, **kwargs):
            self.calls += 1
            raise (classification_error if self.calls == 1 else source_error)("Synthetic mixed failure")

    item = material(origin="human")
    draft = compile_report("topic", "delivery", (item,), MixedService())
    assert draft.coverage["model_calls"] == 2
    assert draft.coverage["rejected_model_calls"] == 1
    assert draft.coverage["unavailable_model_calls"] == 1
    assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"
    assert draft.sections[0]["body"].startswith(item.text)
