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

    item = material()
    draft = compile_report("topic", "Generated event", (item,), ForeignSupport())
    assert "An invented event happened." not in "\n".join(section["body"] for section in draft.sections)
    assert draft.sections[0]["body"].startswith(item.text)
    assert draft.sections[0]["citations"] == item.citations
    assert draft.coverage["rejected_claims"] == 1
    assert draft.coverage["incompletely_analyzed_material_ids"] == (item.material_id,)


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

    note = material(origin="human", citations=())
    draft = compile_report("topic", "delivery", (note,), InvalidClassifier())
    assert draft.sections[0]["body"].startswith(note.text)
    assert "Wrong record." not in draft.sections[0]["body"]
    assert draft.coverage["selected_review_records"] == 0
    assert draft.coverage["classified_review_records"] == 0
    assert draft.coverage["retained_unclassified_review_material_ids"] == (note.material_id,)


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
    unchecked = set(draft.coverage["unclassified_review_material_ids"])
    assert unchecked.isdisjoint(draft.coverage["omitted_human_material_ids"])
    assert set(draft.coverage["retained_unclassified_review_material_ids"]) == unchecked
    for note in notes:
        if note.material_id in unchecked:
            assert any(section["body"].startswith(note.text) for section in draft.sections)


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
    assert notes[0].text in content and notes[1].text in content
    assert draft.coverage['classified_review_records'] == 0
    assert draft.coverage['retained_unclassified_review_material_ids'] == (notes[0].material_id, notes[1].material_id)
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


@pytest.mark.parametrize("kind,topic", [("topic", "delivery"), ("entities", "")])
@pytest.mark.parametrize("failure", ["unavailable", "rejected"])
def test_initially_available_model_failure_preserves_attributed_saved_findings(kind, topic, failure):
    from case_intelligence.generation import GenerationRejected, GenerationUnavailable
    items = (material(), material(2))
    class FailedService:
        available = True
        def answer(self, *args, **kwargs):
            raise (GenerationUnavailable if failure == "unavailable" else GenerationRejected)("Synthetic unavailable answer")
    draft = compile_report(kind, topic, items, FailedService())
    for item in items:
        saved = next(section for section in draft.sections if section.get("material_ids") == (item.material_id,))
        assert saved["body"].startswith(item.text)
        assert item.revision in saved["compilation_basis"]
        assert saved["citations"] == item.citations
    assert draft.coverage["unprocessed_source_passages"] == 2
    assert draft.coverage["unavailable_model_calls"] == draft.coverage["model_calls"]
    assert draft.coverage["stop_reason"] == "analysis_incomplete"
    if topic:
        assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"
        assert "topic relevance has not been checked" in draft.sections[-1]["body"]


@pytest.mark.parametrize("failure", ["budget", "unavailable", "rejected"])
def test_source_entity_categories_remain_incomplete_and_preserve_saved_fallback(failure):
    from case_intelligence.generation import GenerationRejected, GenerationUnavailable
    item = material()
    class PartialService:
        available = True
        def answer(self, question, evidence, **kwargs):
            if "named places" in question:
                raise (GenerationRejected if failure == "rejected" else GenerationUnavailable)("Synthetic unexamined places")
            return VerifiedAnswer(True, "", (VerifiedClaim(evidence[0].excerpt, ("S1",)),), None, "", ("S1",), True, 1)
    draft = compile_report("entities", materials=(item,), generator=PartialService(),
                           budget=CompilationBudget(max_model_calls=1 if failure == "budget" else 3))
    assert any(section.get("category") == "People" for section in draft.sections)
    saved = next(section for section in draft.sections if section.get("category") == "Saved findings awaiting compilation")
    assert saved["body"].startswith(item.text)
    assert draft.coverage["analyzed_source_passages"] == 0
    assert draft.coverage["unprocessed_source_passages"] == 1
    assert draft.coverage["partially_analyzed_source_passages"] == 1
    assert draft.coverage["source_classification_categories"][0]["categories"] == (("People",) if failure == "budget" else ("People", "Things"))
    assert draft.coverage["incompletely_analyzed_material_ids"] == (item.material_id,)
    assert draft.coverage["stop_reason"] == ("budget_reached" if failure == "budget" else "analysis_incomplete")


def test_repeated_generated_provenance_fits_real_report_storage_with_explicit_omissions(tmp_path):
    from case_intelligence.workspace_store import WorkspaceStore
    shared = citation()
    items = tuple(material(index, title="Synthetic title " + "x" * 184, citations=(shared,)) for index in range(1, 201))
    draft = compile_report("entities", materials=items, generator=service())
    generated = [section for section in draft.sections if section.get("category") in {"People", "Places", "Things"}]
    assert len(generated) == 3
    assert draft.coverage["omitted_attribution_count"] == sum(section["omitted_attribution_count"] for section in generated) > 0
    for section in generated:
        assert len(section["compilation_basis"]) <= 40_000
        assert len(section["body"]) <= 50_000
        assert f"Attributions omitted from this section: {section['omitted_attribution_count']}." in section["compilation_basis"]
        assert len(section["material_ids"]) == 200
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler", preferred_principal_id="synthetic-compiler")
        matter = store.create_matter("Synthetic provenance", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter.matter_id, actor.principal_id, title=draft.title,
                                                  purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        assert len(store.report_sections(matter.matter_id, report.report_id)) == 4
    finally:
        store.close()


@pytest.mark.parametrize("markdown_special", [False, True])
def test_repeated_generated_passages_fail_before_export_capacity_is_exceeded(markdown_special):
    from case_intelligence.work_product_exports import MAX_EXPORT_TEXT_CHARS
    marker = "*" if markdown_special else "x"
    source_text = " ".join(f"Synthetic event {index}." for index in range(200)).ljust(6_000, marker)
    class RepeatedSources:
        available = True
        def answer(self, question, evidence, **kwargs):
            ids = tuple(item.evidence_id for item in evidence)
            return VerifiedAnswer(True, "", tuple(VerifiedClaim(f"Synthetic event {index}.", ids)
                                                  for index in range(200)), None, "", ids, True, 1)
    with pytest.raises(CompilationProblem, match="too large to save and export completely"):
        compile_report("topic", "synthetic events", (material(citations=tuple(citation(index, text=source_text) for index in range(1, 13))),),
                       RepeatedSources(), budget=CompilationBudget(max_sections=400))
    small = compile_report("topic", "synthetic events", (material(),), service())
    assert small.coverage["estimated_export_characters"] < small.coverage["export_character_limit"] == MAX_EXPORT_TEXT_CHARS


@pytest.mark.parametrize("selection", ["research:synthetic-investigation", "conversation:synthetic-conversation", "review:synthetic-check"])
def test_offline_focused_fallback_counts_original_saved_work_not_expanded_findings(selection):
    items = (material(), material(2, category="gap", citations=()), material(3, category="coverage", citations=()))
    draft = compile_report("topic", "delivery", items, selections=(selection,))
    assert draft.coverage["selected_saved_work_count"] == 1
    assert draft.coverage["selected_materials"] == 3
    assert draft.coverage["selected_saved_work_ids"] == (selection,)
    assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"
    assert all("relevance not checked" in section["heading"] for section in draft.sections[:-1])
    assert "topic relevance has not been checked" in draft.sections[-1]["body"]
    assert "Selected saved work: 1. Expanded findings compiled: 3 of 3." in draft.sections[-1]["compilation_basis"]
    assert draft.fingerprint == compilation_fingerprint("topic", "delivery", items, selections=(selection,))
    assert draft.fingerprint != compilation_fingerprint("topic", "delivery", items, selections=("research:different-group",))


def test_material_budget_does_not_turn_multiple_saved_work_selections_into_one():
    with pytest.raises(CompilationProblem, match="Topic relevance could not be checked"):
        compile_report("topic", "delivery", (material(), material(2)),
                       selections=("research:first", "research:second"), budget=CompilationBudget(max_materials=1))


@pytest.mark.parametrize("selections", [(), ("research:first", "research:first"), ("",), "research:first"])
def test_selected_work_group_ids_must_be_explicit_and_unique(selections):
    with pytest.raises(CompilationProblem, match="[Ss]elected"):
        compilation_fingerprint("topic", "delivery", (material(),), selections=selections)


class EveryRecordService:
    available = True

    def answer(self, question, evidence, **kwargs):
        claims = tuple(VerifiedClaim(item.excerpt, (item.evidence_id,)) for item in evidence)
        return VerifiedAnswer(True, "", claims, None, "", tuple(item.evidence_id for item in evidence), True, 1)


@pytest.mark.parametrize("use_model", [False, True])
def test_section_capacity_preserves_late_human_review_before_machine_work(use_model):
    note = material(3, origin="human", review_status="disputed", author="Synthetic reviewer",
                    text="The synthetic delivery date remains disputed.", review_details="Compare both accounts.")
    draft = compile_report("timeline", materials=(material(), material(2), note),
                           generator=EveryRecordService() if use_model else None,
                           budget=CompilationBudget(max_sections=1))
    assert len(draft.sections) == 2
    section = draft.sections[0]
    assert section["material_ids"] == (note.material_id,)
    assert section["body"].startswith(note.text)
    assert section["citations"] == note.citations
    assert section["provenance"] == ({"material_id": note.material_id, "origin": "human",
                                      "review_status": "disputed", "revision": note.revision,
                                      "author": note.author},)
    assert note.review_details in section["compilation_basis"]
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["stop_reason"] == "budget_reached"


@pytest.mark.parametrize("max_sections", [2, 4, 6])
def test_entity_category_expansion_keeps_every_human_record_at_capacity(max_sections):
    notes = tuple(material(index, origin="human", citations=(),
                           text=f"Synthetic reviewer {index} saw a blue device at Harbor Annex.")
                  for index in (1, 2))
    draft = compile_report("entities", materials=notes, generator=EveryRecordService(),
                           budget=CompilationBudget(max_sections=max_sections))
    assert len(draft.sections) == max_sections + 1
    for note in notes:
        saved = [section for section in draft.sections if section["material_ids"] == (note.material_id,)]
        assert saved and all(section["body"].startswith(note.text) for section in saved)
        labels = "; ".join(section["category"] for section in saved)
        assert all(category in labels for category in ("People", "Places", "Things"))
    assert draft.coverage["omitted_human_material_ids"] == ()


def test_default_material_and_section_limits_retain_every_human_note():
    notes = tuple(material(index, origin="human", citations=(),
                           text=f"Synthetic reviewer {index} saw a blue device at Harbor Annex.")
                  for index in range(1, 201))
    draft = compile_report("entities", materials=notes, generator=EveryRecordService())
    assert len(draft.sections) == 201
    for note, section in zip(notes, draft.sections):
        assert section["material_ids"] == (note.material_id,)
        assert section["body"].startswith(note.text)
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["omitted_sections"] == 0
    assert draft.coverage["unclassified_review_material_ids"]


def test_human_records_alone_over_capacity_fail_explicitly():
    notes = tuple(material(index, origin="human", citations=()) for index in (1, 2))
    with pytest.raises(CompilationProblem, match="human review.*section budget"):
        compile_report("timeline", materials=notes, budget=CompilationBudget(max_sections=1))


def test_empty_and_topic_excluded_humans_do_not_reserve_sections():
    class RelevantFirstService(EveryRecordService):
        def answer(self, question, evidence, **kwargs):
            return super().answer(question, evidence[:1], **kwargs)

    notes = (material(1, origin="human", citations=()),
             material(2, origin="human", citations=(), text="Unrelated synthetic payroll note."),
             material(3, origin="human", citations=(), text=" "))
    draft = compile_report("topic", "delivery", (*notes, material(4)), RelevantFirstService(),
                           budget=CompilationBudget(max_sections=2))
    assert len(draft.sections) == 3
    assert any(section.get("category") == "Topic findings" for section in draft.sections)
    assert any(section["body"].startswith(notes[0].text) for section in draft.sections)
    assert draft.coverage["omitted_human_material_ids"] == (notes[1].material_id,)
    assert notes[2].material_id not in draft.coverage["retained_unclassified_review_material_ids"]


def test_failed_model_retains_humans_with_reserved_capacity():
    from case_intelligence.generation import GenerationUnavailable

    class FailedService:
        available = True

        def answer(self, *args, **kwargs):
            raise GenerationUnavailable("Synthetic model outage")

    note = material(2, origin="human", citations=())
    draft = compile_report("topic", "delivery", (material(), note), FailedService(),
                           budget=CompilationBudget(max_sections=1))
    assert draft.sections[0]["material_ids"] == (note.material_id,)
    assert draft.sections[0]["body"].startswith(note.text)
    assert draft.coverage["mode"] == "unfiltered_saved_material_arrangement"


@pytest.mark.parametrize("kind", ["topic", "timeline", "entities"])
@pytest.mark.parametrize("failure", ["unavailable", "rejected"])
def test_failed_relevance_check_preserves_dispute_when_source_generation_succeeds(kind, failure):
    from case_intelligence.generation import GenerationRejected, GenerationUnavailable

    class MixedService(EveryRecordService):
        def answer(self, question, evidence, **kwargs):
            if evidence[0].source_name == "Saved review record":
                raise (GenerationUnavailable if failure == "unavailable" else GenerationRejected)("Synthetic classification failure")
            return super().answer(question, evidence, **kwargs)

    note = material(2, origin="human", review_status="disputed", author="Synthetic reviewer",
                    text="The synthetic delivery date is disputed.")
    draft = compile_report(kind, "delivery", (material(), note), MixedService(),
                           budget=CompilationBudget(max_sections=2))
    saved = next(section for section in draft.sections if section["body"].startswith(note.text))
    assert saved["material_ids"] == (note.material_id,)
    assert saved["citations"] == note.citations
    assert note.author in saved["compilation_basis"]
    assert "relevance has not been fully checked" in saved["compilation_basis"]
    assert "disputed" in saved["compilation_basis"]
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["retained_unclassified_review_material_ids"] == (note.material_id,)
    assert draft.coverage["mode"] == "model_assisted"
    assert "retained without a complete topic relevance check" in draft.sections[-1]["body"]


def test_partial_entity_relevance_does_not_exclude_unchecked_disagreement():
    from case_intelligence.generation import GenerationUnavailable

    class PartialService(EveryRecordService):
        def answer(self, question, evidence, **kwargs):
            if evidence[0].source_name == "Saved review record":
                if "named places" in question:
                    raise GenerationUnavailable("Synthetic unavailable Places classification")
                return VerifiedAnswer(False, "", (), None, "No related mention identified.", (), True, 1)
            return super().answer(question, evidence, **kwargs)

    note = material(2, origin="human", review_status="disputed", text="Synthetic reviewers dispute the delivery location.")
    draft = compile_report("entities", "delivery", (material(), note), PartialService())
    saved = next(section for section in draft.sections if section["body"].startswith(note.text))
    assert saved["category"] == "Unclassified review notes"
    assert "relevance has not been fully checked" in saved["compilation_basis"]
    assert draft.coverage["classified_review_records"] == 0
    assert draft.coverage["partially_classified_review_material_ids"] == (note.material_id,)
    assert draft.coverage["omitted_human_material_ids"] == ()
    assert draft.coverage["retained_unclassified_review_material_ids"] == (note.material_id,)


@pytest.mark.parametrize("origin,status", [("research", "verified"), ("human", "disputed")])
def test_oversized_citations_fail_before_model_work(origin, status):
    class UnexpectedService:
        @property
        def available(self):
            pytest.fail("Oversized citations must be rejected before consulting the model")

    item = material(origin=origin, review_status=status, citations=(citation(text="x" * 6_001),))
    with pytest.raises(CompilationProblem, match="6,000-character.*citation"):
        compile_report("timeline", materials=(item,), generator=UnexpectedService())


@pytest.mark.parametrize("use_model", [False, True])
def test_exact_citation_size_limit_compiles_and_persists_without_shortening(tmp_path, use_model):
    from case_intelligence.workspace_store import WorkspaceStore

    item = material(citations=(citation(text="Synthetic delivery source. ".ljust(6_000, "x")),))
    draft = compile_report("timeline", materials=(item,), generator=EveryRecordService() if use_model else None)
    assert draft.sections[0]["citations"] == item.citations
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler", preferred_principal_id="synthetic-compiler")
        matter = store.create_matter("Synthetic citation capacity", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter.matter_id, actor.principal_id, title=draft.title,
                                                  purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        saved_sections = store.report_sections(matter.matter_id, report.report_id)
        assert len(saved_sections) == len(draft.sections)
        assert store.report_citations(matter.matter_id, report.report_id, saved_sections[0].section_id)[0].excerpt == item.citations[0]["excerpt"]
    finally:
        store.close()
