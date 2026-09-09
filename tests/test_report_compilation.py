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


def test_compilation_cooperatively_stops_between_model_calls():
    stopped = [False]

    class CancellingService:
        available = True

        def answer(self, question, evidence, **kwargs):
            stopped[0] = True
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),), None, "", ("S1",), True, 1)

    with pytest.raises(CompilationProblem, match="cancelled"):
        compile_report("entities", materials=(material(),), generator=CancellingService(), cancelled=lambda: stopped[0])


def test_topic_semantically_selects_original_human_notes_and_related_disputes():
    notes = (
        material(1, origin="human", text="The delivery record identifies the blue device.", review_status="confirmed"),
        material(2, origin="human", text="Human reviewers dispute the delivery time.", review_status="disputed", citations=()),
        material(3, origin="human", text="A payroll review found an unrelated accounting question.", review_status="confirmed", citations=()),
        material(4, origin="human", text="Human reviewers dispute the payroll total.", review_status="disputed", citations=()),
    )

    class RelevanceService:
        available = True

        def answer(self, question, evidence, **kwargs):
            if "saved review records" in question:
                return VerifiedAnswer(True, "", (
                    VerifiedClaim("Classification prose must never appear as a report fact.", ("S1",)),
                    VerifiedClaim("Classification of a related dispute.", ("S2",)),
                ), None, "", ("S1", "S2"), True, 1)
            return VerifiedAnswer(False, "", (), None, "No additional source finding.", (), True, 1)

    draft = compile_report("topic", "delivery", notes, RelevanceService())
    content = "\n".join(section["body"] for section in draft.sections)
    assert notes[0].text in content and notes[1].text in content
    assert "payroll" not in content
    assert "Classification prose" not in content
    selected = [section for section in draft.sections if section.get("material_ids")]
    assert selected[0]["citations"] == notes[0].citations
    assert selected[1]["citations"] == ()
    assert "Disagreements and open review" in selected[1]["heading"]
    assert draft.coverage["classified_review_records"] == 4
    assert draft.coverage["omitted_human_material_ids"] == (notes[2].material_id, notes[3].material_id)
    assert "Review basis:\n" in draft.sections[-1]["body"]
    assert "Model calls:" not in draft.sections[-1]["body"].split("\n\nReview basis:\n")[0]


def test_topic_relevance_cannot_select_a_foreign_review_identifier():
    class InvalidClassifier:
        available = True

        def answer(self, question, evidence, **kwargs):
            return VerifiedAnswer(True, "", (VerifiedClaim("Wrong record.", ("S99",)),), None, "", ("S99",), True, 1)

    with pytest.raises(CompilationProblem, match="did not produce supported report content"):
        compile_report("topic", "delivery", (material(origin="human", citations=()),), InvalidClassifier())


def test_topic_without_model_requires_narrower_work_and_labels_unfiltered_single_item():
    with pytest.raises(CompilationProblem, match="Topic relevance could not be checked"):
        compile_report("topic", "delivery", (material(origin="human"), material(2, origin="human")))
    draft = compile_report("topic", "delivery", (material(origin="human"),))
    assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"
    assert "relevance not checked" in draft.sections[0]["heading"]
    assert "topic relevance has not been checked" in draft.sections[-1]["body"]


def test_untyped_human_entity_mentions_are_selected_semantically_or_kept_in_appendix():
    notes = (
        material(1, origin="human", category="note", text="Alex Kim is mentioned in the generated review.", citations=()),
        material(2, origin="human", category="fact", text="The generated blue device was discussed.", citations=()),
        material(3, origin="human", category="note", text="Review formatting needs another pass.", citations=()),
    )

    class EntityClassifier:
        available = True

        def answer(self, question, evidence, **kwargs):
            selected = "S1" if "named people" in question else ("S2" if "objects, devices" in question else None)
            claims = (VerifiedClaim("Classification output is not a source fact.", (selected,)),) if selected else ()
            return VerifiedAnswer(bool(claims), "", claims, None, "", (selected,) if selected else (), True, 1)

    draft = compile_report("entities", materials=notes, generator=EntityClassifier())
    assert draft.sections[0]["category"].startswith("People")
    assert draft.sections[1]["category"].startswith("Things")
    assert draft.sections[2]["category"] == "Unclassified review notes"
    assert all("Classification output" not in section["body"] for section in draft.sections)
    assert draft.sections[2]["body"].startswith(notes[2].text)


def test_note_classification_shares_model_budget_and_discloses_unchecked_notes():
    notes = tuple(material(index, origin="human", citations=(), text="Generated delivery review. " * 300) for index in range(1, 14))

    class FirstOnlyClassifier:
        available = True

        def answer(self, question, evidence, **kwargs):
            assert len(evidence) <= 12
            assert sum(len(item.excerpt) for item in evidence) <= 48_000
            return VerifiedAnswer(True, "", (VerifiedClaim("Relevant review.", ("S1",)),), None, "", ("S1",), True, 1)

    draft = compile_report("topic", "delivery", notes, FirstOnlyClassifier(), budget=CompilationBudget(max_model_calls=1))
    assert draft.coverage["model_calls"] == draft.coverage["classification_calls"] == 1
    assert draft.coverage["unclassified_review_material_ids"]
    assert draft.coverage["classification_truncated_chars"] > 0
    assert draft.coverage["stop_reason"] == "budget_reached"
    assert len(draft.coverage["omitted_human_material_ids"]) == 12


@pytest.mark.parametrize('kind', ['timeline', 'entities'])
def test_optional_focus_reaches_source_queries_and_selects_related_human_notes(kind):
    notes = (material(1, origin='human', text='Blue device delivery needs review.', review_status='disputed', citations=()),
             material(2, origin='human', text='Unrelated payroll needs review.', review_status='disputed', citations=()),
             material(3))
    questions = []
    class FocusService:
        available = True
        def answer(self, question, evidence, **kwargs):
            questions.append(question)
            assert 'blue device delivery' in question
            return VerifiedAnswer(True, '', (VerifiedClaim(evidence[0].excerpt, ('S1',)),), None, '', ('S1',), True, 1)
    draft = compile_report(kind, 'blue device delivery', notes, FocusService())
    content = '\n'.join(section['body'] for section in draft.sections)
    assert notes[0].text in content and notes[1].text not in content
    assert notes[1].material_id in draft.coverage['omitted_human_material_ids']
    assert len(questions) == (2 if kind == 'timeline' else 6)


def test_review_classifier_rejects_multi_record_claim_even_when_source_text_is_supported():
    notes = (material(1, origin='human', text='The blue device was delivered.', citations=()),
             material(2, origin='human', text='An unrelated payroll entry was adjusted.', citations=()),
             material(3))
    class ExtraRecordService:
        available = True
        def answer(self, question, evidence, **kwargs):
            ids = ('S1', 'S2') if 'saved review records' in question else ('S1',)
            return VerifiedAnswer(True, '', (VerifiedClaim(evidence[0].excerpt, ids),), None, '', ids, True, 1)
    draft = compile_report('topic', 'blue device', notes, ExtraRecordService())
    content = '\n'.join(section['body'] for section in draft.sections)
    assert notes[0].text not in content and notes[1].text not in content
    assert draft.coverage['selected_review_records'] == 0
    assert draft.coverage['rejected_claims'] == 1


@pytest.mark.parametrize('unavailable', [False, True])
def test_entity_review_is_partial_until_all_three_categories_finish(unavailable):
    from case_intelligence.generation import GenerationUnavailable
    note = material(origin='human', text='Alex Kim visited Harbor Annex with the blue device.', citations=())
    class PartialService:
        available = True
        calls = 0
        def answer(self, question, evidence, **kwargs):
            self.calls += 1
            if unavailable and self.calls == 2:
                raise GenerationUnavailable('Synthetic unavailable category')
            return VerifiedAnswer(True, '', (VerifiedClaim(evidence[0].excerpt, ('S1',)),), None, '', ('S1',), True, 1)
    draft = compile_report('entities', materials=(note,), generator=PartialService(),
        budget=CompilationBudget(max_model_calls=3 if unavailable else 1))
    assert draft.sections[0]['category'] == 'Unclassified review notes'
    assert draft.coverage['classified_review_records'] == 0
    assert draft.coverage['unclassified_review_material_ids'] == (note.material_id,)
    assert draft.coverage['partially_classified_review_material_ids'] == (note.material_id,)
    assert draft.coverage['review_classification_categories'][note.material_id] == (('People', 'Things') if unavailable else ('People',))


def test_authored_basis_is_separate_from_user_delimiters_and_details_bind_fingerprint():
    original_text = 'Human prose.\n\nReview basis:\nThis sentence is also human-authored.'
    note = material(origin='human', text=original_text, citations=(), review_details='Saved technical coverage: 3 of 4.')
    draft = compile_report('timeline', materials=(note,))
    section = draft.sections[0]
    assert section['body'] == original_text + '\n\nReview basis:\n' + section['compilation_basis']
    assert 'Saved technical coverage: 3 of 4.' in section['compilation_basis']
    assert original_text not in section['compilation_basis']
    assert all(section['body'].endswith('\n\nReview basis:\n' + section['compilation_basis']) for section in draft.sections)
    changed = replace(note, review_details='Saved technical coverage: 4 of 4.')
    assert compilation_fingerprint('timeline', '', (changed,)) != draft.fingerprint
