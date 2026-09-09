"""Synthetic date-bound and empty-review coverage regressions."""
import pytest

from case_intelligence.generation import GroundedGenerationService, MAX_EVIDENCE_ITEM_CHARS
from case_intelligence.report_compilation import compile_report
from tests.test_report_compilation import citation, material, service


@pytest.mark.parametrize("bounded", [
    "The synthetic delivery occurred no later than 2024-04-02.",
    "The synthetic delivery occurred not later than 2024-04-02.",
    "The synthetic delivery occurred no earlier than 2024-04-02.",
    "The synthetic delivery occurred by 2024-04-02.",
    "The synthetic delivery occurred on 2024-04-02 at the latest.",
    "The synthetic delivery occurred on 2024-04-02 at the earliest.",
    "The synthetic delivery occurred roughly on 2024-04-02.",
    "The synthetic delivery occurred approx. 2024-04-02.",
    "The synthetic delivery occurred as late as 2024-04-02.",
    "The synthetic delivery occurred as early as 2024-04-02.",
    "The synthetic delivery occurred prior to 2024-04-02.",
    "The synthetic delivery occurred up to 2024-04-02.",
])
@pytest.mark.parametrize("path", ["saved", "generated", "limitation"])
def test_bound_or_approximation_never_receives_an_exact_date(bounded, path):
    statement = "The synthetic delivery occurred on 2024-04-02."

    class BoundedClient:
        available = True

        def generate(self, **kwargs):
            return {"answerable": True,
                    "claims": [{"text": statement if path == "limitation" else bounded, "evidence_ids": ["S1"]}],
                    "limitation": {"text": bounded, "evidence_ids": ["S1"]} if path == "limitation" else None,
                    "missing_information": ""}

    item = material(text=bounded, date_label="2024-04-02",
                    citations=(citation(text=statement + " " + bounded),))
    draft = compile_report("timeline", materials=(item,),
                           generator=None if path == "saved" else GroundedGenerationService(BoundedClient()))
    assert draft.sections[0]["date_key"] == ""
    assert "2024-04-02" not in draft.sections[0]["heading"]
    assert bounded in draft.sections[0]["body"]


@pytest.mark.parametrize("kind", ["topic", "timeline", "entities"])
@pytest.mark.parametrize("blank", ["", " \t\n ", " " * (MAX_EVIDENCE_ITEM_CHARS + 1)],
                         ids=["empty", "whitespace", "long_whitespace"])
@pytest.mark.parametrize("origin,category", [("human", ""), ("research", "gap")])
def test_blank_review_records_do_not_make_complete_analysis_incomplete(kind, blank, origin, category):
    supported = material(1, origin="human", citations=(), text="Synthetic reviewer Alex disputes delivery of the blue device at Harbor Annex.")
    empty = material(2, origin=origin, category=category, text=blank, citations=())
    draft = compile_report(kind, "blue device delivery", (supported, empty), service())
    assert draft.coverage["stop_reason"] == "compiled_selected_material"
    assert draft.coverage["classified_review_records"] == 1
    assert draft.coverage["selected_review_records"] == 1
    assert draft.coverage["unclassified_review_material_ids"] == ()
    assert draft.coverage["partially_classified_review_material_ids"] == ()
    assert draft.coverage["retained_unclassified_review_material_ids"] == ()
    assert draft.coverage["truncated_review_material_ids"] == ()
    assert draft.coverage["classification_truncated_chars"] == 0
    assert empty.material_id not in draft.coverage["review_classification_categories"]
    assert all(empty.material_id not in section["material_ids"] for section in draft.sections)
    ledger = draft.sections[-1]["body"]
    assert "Review records checked: 1 of 1" in ledger
    assert "unchecked review records: 0" in ledger


def test_blank_prefix_does_not_hide_real_review_text_after_truncation():
    supported = material(1, origin="human", citations=(), text="Synthetic reviewer disputes the delivery.")
    late = material(2, origin="human", citations=(),
                    text=" " * MAX_EVIDENCE_ITEM_CHARS + "The synthetic delivery remains disputed.")
    draft = compile_report("topic", "delivery", (supported, late), service())
    assert draft.coverage["stop_reason"] == "analysis_incomplete"
    assert draft.coverage["unclassified_review_material_ids"] == (late.material_id,)
    assert draft.coverage["truncated_review_material_ids"] == (late.material_id,)
    assert draft.coverage["retained_unclassified_review_material_ids"] == (late.material_id,)
    assert any(section["body"].startswith(late.text) for section in draft.sections)


def test_actor_attribution_with_by_keeps_an_explicit_date_exact():
    text = "The synthetic delivery was recorded by Alex on 2024-04-02."
    draft = compile_report("timeline", materials=(material(text=text, citations=(citation(text=text),)),), generator=service())
    assert draft.sections[0]["date_key"] == "2024-04-02"
