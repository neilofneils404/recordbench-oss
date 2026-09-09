"""Synthetic regressions for qualified chronology and incomplete analysis."""
import pytest

from case_intelligence.generation import EvidenceItem, GroundedGenerationService
from case_intelligence.report_compilation import compile_report
from tests.test_report_compilation import citation, material, service


@pytest.mark.parametrize("wording", [
    "The delivery may have occurred on 2024-04-02.",
    "The delivery might have occurred on 2024-04-02.",
    "The approximate delivery date is 2024-04-02.",
    "The estimated delivery date is 2024-04-02.",
    "The delivery occurred circa 2024-04-02.",
    "The delivery date 2024-04-02 is uncertain.",
    "The delivery date 2024-04-02 remains unconfirmed.",
])
@pytest.mark.parametrize("generated", [False, True])
def test_uncertain_dates_never_receive_exact_sort_keys(wording, generated):
    selected = material(text=wording, date_label="2024-04-02", citations=(citation(text=wording),))
    draft = compile_report("timeline", materials=(selected,), generator=service() if generated else None)
    finding = draft.sections[0]
    assert finding["date_key"] == ""
    assert "2024-04-02" not in finding["heading"]
    assert wording in finding["body"]


@pytest.mark.parametrize("limitation", [
    "The delivery date is approximate.",
    "The delivery date is uncertain.",
    "The delivery date remains unconfirmed.",
])
def test_verified_limitation_prevents_exact_heading_and_sorting(limitation):
    statement = "The synthetic delivery occurred on 2024-04-02."

    class QualifiedClient:
        available = True

        def generate(self, *, evidence, **kwargs):
            return {"answerable": True,
                    "claims": [{"text": statement, "evidence_ids": ["S1"]}],
                    "limitation": {"text": limitation, "evidence_ids": ["S1"]},
                    "missing_information": ""}

    uncertain = material(citations=(citation(text=statement + " " + limitation),))
    exact = material(2, origin="human", text="The synthetic review occurred on 2024-05-01.", citations=())
    draft = compile_report("timeline", materials=(uncertain, exact), generator=GroundedGenerationService(QualifiedClient()))
    assert draft.sections[0]["date_key"] == "2024-05-01"
    finding = next(section for section in draft.sections if section.get("category") == "Chronology")
    assert finding["date_key"] == ""
    assert finding["heading"] == "Chronology — dates as stated"
    assert "Limitation: " + limitation in finding["body"]


@pytest.mark.parametrize("kind", ["topic", "timeline", "entities"])
def test_classifier_limitation_retains_ambiguous_unreturned_note(kind):
    class AmbiguousClassifier:
        available = True

        def generate(self, *, evidence, **kwargs):
            return {"answerable": True,
                    "claims": [{"text": evidence[0].excerpt, "evidence_ids": ["S1"]}],
                    "limitation": {"text": evidence[1].excerpt, "evidence_ids": ["S2"]},
                    "missing_information": ""}

    notes = (material(1, origin="human", citations=(), text="The synthetic reviewer disputes the delivery."),
             material(2, origin="human", citations=(), text="The relevance of this synthetic delivery note remains ambiguous."))
    draft = compile_report(kind, "delivery", notes, GroundedGenerationService(AmbiguousClassifier()))
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["classified_review_records"] == 0
    for note in notes:
        section = next(section for section in draft.sections if section["body"].startswith(note.text))
        assert "relevance has not been fully checked" in section["compilation_basis"]
        assert note.material_id in draft.coverage["retained_unclassified_review_material_ids"]


@pytest.mark.parametrize("identifiers", [["S2", "S1"], ["S1", "S2"]])
def test_reversed_duplicate_preserves_unrepresented_source_finding(identifiers):
    statement = "The synthetic delivery was recorded."

    class ReversedDuplicateClient:
        available = True

        def generate(self, **kwargs):
            return {"answerable": True, "claims": [
                {"text": statement, "evidence_ids": ["S1", "S2"]},
                {"text": statement, "evidence_ids": identifiers},
            ], "limitation": None, "missing_information": ""}

    selected = tuple(material(index, text=f"Synthetic saved delivery finding {index}.",
                              citations=(citation(index, text=statement),)) for index in (1, 2, 3))
    generator = GroundedGenerationService(ReversedDuplicateClient())
    evidence = tuple(EvidenceItem(f"S{index}", "Synthetic source", "Line 1", statement) for index in (1, 2, 3))
    answer = generator.answer("delivery", evidence)
    assert answer.duplicate_claims == 1
    assert answer.omitted_claims == 0
    assert len(answer.claims) == 1
    assert answer.claims[0].evidence_ids == ("S1", "S2")
    draft = compile_report("topic", "delivery", selected, generator)
    generated = [section for section in draft.sections if section["body"].startswith(statement)]
    assert len(generated) == 1
    assert generated[0]["citations"] == (selected[0].citations[0], selected[1].citations[0])
    assert any(section["body"].startswith(selected[2].text) for section in draft.sections)
    assert selected[2].material_id in draft.coverage["incompletely_analyzed_material_ids"]
    assert draft.coverage["stop_reason"] == "analysis_incomplete"


@pytest.mark.parametrize("statement,limitation,expected", [
    ("The synthetic delivery occurred on 2024-04-02.", "The device color is unknown.", "2024-04-02"),
    ("The synthetic delivery occurred.", "The review date is 2024-04-02.", ""),
])
def test_limitation_neither_invents_a_date_nor_removes_an_unqualified_date(statement, limitation, expected):
    class QualifiedClient:
        available = True

        def generate(self, **kwargs):
            return {"answerable": True, "claims": [{"text": statement, "evidence_ids": ["S1"]}],
                    "limitation": {"text": limitation, "evidence_ids": ["S1"]}, "missing_information": ""}

    draft = compile_report("timeline", materials=(material(citations=(citation(text=statement + " " + limitation),)),),
                           generator=GroundedGenerationService(QualifiedClient()))
    assert draft.sections[0]["date_key"] == expected


def test_verifier_preserves_distinct_text_and_distinct_evidence_sets():
    first = "The synthetic delivery was recorded."
    second = "The synthetic inspection was recorded."
    evidence = tuple(EvidenceItem(f"S{index}", "Synthetic source", "Line 1", first + " " + second)
                     for index in (1, 2))
    raw = {"answerable": True, "claims": [
        {"text": first, "evidence_ids": ["S1"]},
        {"text": first, "evidence_ids": ["S2"]},
        {"text": second, "evidence_ids": ["S1"]},
    ], "limitation": None, "missing_information": ""}
    answer = GroundedGenerationService._verify(raw, evidence, 1)
    assert len(answer.claims) == 3
    assert answer.duplicate_claims == 0
    assert answer.omitted_claims == 0
