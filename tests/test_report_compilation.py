"""Synthetic regressions for grounded automatic report compilation."""
from dataclasses import replace

import pytest

from case_intelligence.generation import (
    GroundedGenerationService, VerifiedAnswer, VerifiedClaim,
)
from case_intelligence.report_compilation import (
    CompilationBudget, CompilationMaterial, CompilationProblem,
    compilation_fingerprint, compile_report,
)


def citation(index=1, text="On 2024-04-02, Alex Kim delivered the blue device to Harbor Annex."):
    return {"kind": "source", "document_id": f"{index:032x}", "source_version_id": f"{index+100:032x}",
            "support_token": f"{index:040x}", "source_name": f"Generated source {index}.txt", "location": "Line 1",
            "excerpt": text}


def material(index=1, **changes):
    values = {"material_id": f"synthetic-material-{index}", "origin": "research", "title": "Generated finding",
              "text": "The generated delivery is documented.", "citations": (citation(index),),
              "review_status": "verified", "revision": "synthetic-revision-1"}
    values.update(changes)
    return CompilationMaterial(**values)


class SourceEchoClient:
    available = True

    def generate(self, *, question, evidence, **kwargs):
        return {"answerable": True, "claims": [
            {"text": item.excerpt, "evidence_ids": [item.evidence_id]}
            for item in evidence[:2]
        ], "limitation": None, "missing_information": ""}


def service():
    return GroundedGenerationService(SourceEchoClient())


def test_timeline_compiles_source_events_and_preserves_human_disagreement():
    uncertain = citation(2, "Around 2024-04-03, a second account placed the blue device at Harbor Annex.")
    note = material(3, origin="human", author="Synthetic reviewer", review_status="disputed", revision="note-revision-2",
                    text="These generated source accounts disagree about the delivery date.", citations=(citation(), uncertain))
    draft = compile_report("timeline", materials=(material(), material(2, citations=(uncertain,)), note), generator=service())
    assert draft.title == "Timeline"
    events = [section for section in draft.sections if section.get("category") == "Chronology"]
    assert len(events) == 2
    assert events[0]["date_key"] == "2024-04-02"
    assert events[1]["date_key"] == ""
    assert "Around 2024-04-03" in events[1]["body"]
    disagreement = next(section for section in draft.sections if section.get("category") == "Disagreements and open review")
    assert note.text in disagreement["body"]
    assert "Human review by Synthetic reviewer" in disagreement["body"]
    assert "note-revision-2" in disagreement["body"]
    assert disagreement["citations"] == note.citations
    assert draft.coverage["mode"] == "model_assisted"


def test_people_places_things_use_semantic_queries_and_keep_ambiguous_mentions_separate():
    first = material()
    second = material(2, citations=(citation(2, "A different Alex Kim inspected a red device at North Annex."),))
    draft = compile_report("entities", materials=(first, second), generator=service())
    for category in ("People", "Places", "Things"):
        found = [section for section in draft.sections if section.get("category") == category]
        assert len(found) == 2
        assert found[0]["citations"] == first.citations
        assert found[1]["citations"] == second.citations
        assert found[0]["material_ids"] != found[1]["material_ids"]
    assert draft.coverage["model_calls"] == 3


def test_topic_uses_only_material_cited_by_its_verified_findings():
    class TopicService:
        available = True

        def answer(self, question, evidence, **kwargs):
            assert "blue device" in question
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),), None, "", ("S1",), True, 1)

    relevant = material()
    other = material(2, text="Generated unrelated inventory.", citations=(citation(2, "A green cabinet was inventoried."),))
    draft = compile_report("topic", "blue device", (relevant, other), TopicService())
    content = "\n".join(section["body"] for section in draft.sections)
    assert "green cabinet" not in content
    assert "Generated unrelated inventory" not in content
    assert draft.sections[0]["citations"] == relevant.citations
    assert draft.coverage["uncompiled_material_ids"] == (other.material_id,)


def test_model_cannot_attach_foreign_citation_ids():
    class ForeignSupport:
        available = True

        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim("An invented event happened.", ("S9",)),), None, "", ("S9",), True, 1)

    with pytest.raises(CompilationProblem, match="did not produce supported report content"):
        compile_report("topic", "Generated event", (material(),), ForeignSupport())


def test_offline_arrangement_is_explicit_and_human_types_are_retained():
    person = material(origin="human", category="person", text="The generated person mention needs source comparison.", review_status="confirmed")
    draft = compile_report("entities", materials=(person, material(2)))
    assert draft.coverage["mode"] == "saved_material_arrangement"
    assert draft.coverage["model_calls"] == 0
    assert any(section.get("category") == "People — human review" for section in draft.sections)
    assert any("arranged without AI" in section["heading"] for section in draft.sections)


def test_preview_fingerprint_changes_for_every_basis_revision_and_scope_change():
    basis = material()
    original = compilation_fingerprint("timeline", "", (basis,))
    changes = (
        replace(basis, revision="synthetic-revision-2"), replace(basis, text="Changed saved review."),
        replace(basis, review_status="disputed"), replace(basis, origin="human"),
        replace(basis, citations=(citation(3),)), replace(basis, author="Another synthetic reviewer"),
    )
    for changed in changes:
        assert compilation_fingerprint("timeline", "", (changed,)) != original
    assert compilation_fingerprint("topic", "devices", (basis,)) != original
    assert compilation_fingerprint("timeline", "", (basis,), budget=CompilationBudget(max_materials=1)) != original
    assert compile_report("timeline", materials=(basis,)).fingerprint == original


def test_work_budget_discloses_omissions_and_covers_full_selection_in_fingerprint():
    items = tuple(material(index) for index in range(1, 5))
    policy = CompilationBudget(max_materials=2, max_model_calls=1, max_sections=1)
    draft = compile_report("entities", materials=items, generator=service(), budget=policy)
    assert draft.coverage["omitted_material_ids"] == (items[2].material_id, items[3].material_id)
    assert draft.coverage["model_calls"] == 1
    assert draft.coverage["stop_reason"] == "budget_reached"
    assert len(draft.sections) == 2  # One content section and a complete coverage ledger.
    changed_omission = (*items[:3], replace(items[3], revision="changed-omitted-revision"))
    assert compilation_fingerprint("entities", "", changed_omission, budget=policy) != draft.fingerprint


def test_compiler_source_snapshot_cannot_be_changed_by_model_callback():
    original = material()
    saved_text = original.citations[0]["excerpt"]

    class MutatingService:
        available = True

        def answer(self, question, evidence, **kwargs):
            original.citations[0]["excerpt"] = "Changed external material during compilation."
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),), None, "", ("S1",), True, 1)

    draft = compile_report("timeline", materials=(original,), generator=MutatingService())
    assert draft.sections[0]["citations"][0]["excerpt"] == saved_text
    assert compilation_fingerprint("timeline", "", (original,)) != draft.fingerprint


def test_conflicting_same_locator_and_duplicate_material_identity_fail_closed():
    first = material()
    conflict = material(2, citations=({**citation(), "excerpt": "Conflicting generated source text."},))
    with pytest.raises(CompilationProblem, match="conflicting saved content"):
        compile_report("timeline", materials=(first, conflict))
    with pytest.raises(CompilationProblem, match="identifiers must be unique"):
        compile_report("timeline", materials=(first, first))


def test_unsourced_machine_claim_is_not_compiled_as_a_fact():
    with pytest.raises(CompilationProblem, match="did not produce supported report content"):
        compile_report("timeline", materials=(material(citations=()),))


@pytest.mark.parametrize("kind,topic", [("other", ""), ("topic", "")])
def test_invalid_requests_are_explicit(kind, topic):
    with pytest.raises(CompilationProblem):
        compile_report(kind, topic, (material(),))


def test_saved_gaps_are_preserved_without_promoting_them_to_new_source_findings():
    gap = material(2, category="gap", citations=(), text="The saved investigation could not verify a delivery time.")
    draft = compile_report("topic", "delivery", (material(), gap), service())
    preserved = next(section for section in draft.sections if section.get("category") == "Saved review gaps and limits")
    assert gap.text in preserved["body"]
    assert preserved["citations"] == ()
    assert "Review basis:\n" in preserved["body"]
    assert gap.material_id in preserved["body"]


def test_human_uncertain_date_does_not_gain_precision_from_date_label():
    uncertain = material(origin="human", date_label="2024-04-03", text="Around 2024-04-03 the generated delivery occurred.")
    draft = compile_report("timeline", materials=(uncertain,))
    assert draft.sections[0]["date_key"] == ""
