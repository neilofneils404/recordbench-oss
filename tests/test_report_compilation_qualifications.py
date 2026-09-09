"""Synthetic coverage for finding qualifications surviving Report compilation."""
from dataclasses import replace

import pytest

from case_intelligence.generation import (
    MEDIA_TRANSCRIPT_NOTICE, EvidenceItem, GroundedGenerationService, VerifiedAnswer, VerifiedClaim,
)
from case_intelligence.report_compilation import (
    CompilationBudget, CompilationMaterial, CompilationProblem, compile_report,
)
from case_intelligence.work_product_exports import export_report
from case_intelligence.workspace_store import WorkspaceStore


def material(index=1, *, transcript=False):
    text = ("The machine transcript mentions a synthetic delivery." if transcript
            else "The synthetic delivery date remains unconfirmed.")
    return CompilationMaterial(
        material_id=f"synthetic-record-{index}", origin="research", title="Synthetic finding",
        text=text, review_status="verified", revision="synthetic-revision-1",
        citations=({"kind": "transcript" if transcript else "source",
                    "document_id": f"{index:032x}", "source_version_id": f"{index + 100:032x}",
                    "support_token": f"{index:040x}", "source_name": f"Synthetic source {index}.txt",
                    "location": "00:01–00:02" if transcript else "Line 1", "excerpt": text},),
    )


class AnswerService:
    available = True

    def __init__(self, answer):
        self.result = answer

    def answer(self, question, evidence, **kwargs):
        return self.result


def qualified_answer():
    return VerifiedAnswer(
        True, "", (VerifiedClaim("The machine transcript mentions a synthetic delivery.", ("S1",)),
                   VerifiedClaim("A second synthetic finding was retained.", ("S1",))),
        VerifiedClaim("The synthetic delivery date remains unconfirmed.", ("S2", "S2")),
        "", ("S1", "S2"), True, 1, evidence_notice=MEDIA_TRANSCRIPT_NOTICE,
    )


def test_capacity_retains_qualification_and_its_support_with_each_finding(tmp_path):
    selected = (material(transcript=True), material(2))
    answer = qualified_answer()
    draft = compile_report("timeline", materials=selected, generator=AnswerService(answer),
                           budget=CompilationBudget(max_sections=1))
    assert len(draft.sections) == 2
    finding = draft.sections[0]
    assert "Limitation: " + answer.limitation.text in finding["body"]
    assert "Limitation source support: Source 2." in finding["body"]
    assert "Evidence notice: " + MEDIA_TRANSCRIPT_NOTICE in finding["body"]
    assert finding["citations"] == tuple(item.citations[0] for item in selected)
    assert draft.coverage["omitted_sections"] > 0

    store = WorkspaceStore(tmp_path / "synthetic-workspace.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler",
                                       preferred_principal_id="synthetic-compiler")
        matter_record = store.create_matter("Synthetic qualifications", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter_record.matter_id, actor.principal_id,
            title=draft.title, purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        saved = store.report_sections(matter_record.matter_id, report.report_id)
        assert saved[0].body == finding["body"]
        sections = tuple((section, store.report_citations(matter_record.matter_id, report.report_id, section.section_id))
                         for section in saved)
        assert tuple(citation.excerpt for citation in sections[0][1]) == tuple(item.citations[0]["excerpt"] for item in selected)
        exported = export_report(matter_record, report, sections, "markdown").body.decode("utf-8")
        assert "Limitation: " + answer.limitation.text in exported
        assert "Limitation source support: Source 2." in exported
        assert MEDIA_TRANSCRIPT_NOTICE in exported
    finally:
        store.close()


def test_service_authored_omission_limitation_needs_no_invented_source():
    limitation = VerifiedClaim("Some generated statements were omitted because their source support could not be verified.", ())
    answer = replace(qualified_answer(), limitation=limitation, omitted_claims=1, evidence_notice="")
    draft = compile_report("timeline", materials=(material(),), generator=AnswerService(answer))
    findings = [section for section in draft.sections if section.get("category") == "Chronology"]
    assert len(findings) == 2
    for finding in findings:
        assert "Limitation: " + limitation.text in finding["body"]
        assert "Limitation source support:" not in finding["body"]
        assert finding["citations"] == material().citations


def test_limitation_support_does_not_merge_distinct_claim_support_sets():
    answer = replace(qualified_answer(),
        claims=tuple(VerifiedClaim("A synthetic finding.", (identifier,)) for identifier in ("S1", "S2")),
        limitation=VerifiedClaim("A shared synthetic qualification.", ("S1", "S2")), evidence_notice="")
    selected = (material(), material(2))
    draft = compile_report("timeline", materials=selected, generator=AnswerService(answer))
    findings = [section for section in draft.sections if section.get("category") == "Chronology"]
    assert len(findings) == 2
    assert findings[0]["citations"] == tuple(item.citations[0] for item in selected)
    assert findings[1]["citations"] == tuple(item.citations[0] for item in reversed(selected))
    assert "Limitation source support: Source 1, Source 2." in findings[0]["body"]
    assert "Limitation source support: Source 2, Source 1." in findings[1]["body"]


@pytest.mark.parametrize("identifiers", [("S99",), ("S2", "S99")])
def test_foreign_limitation_support_cannot_leave_an_unqualified_finding(identifiers):
    answer = replace(qualified_answer(), limitation=VerifiedClaim("Synthetic qualification.", identifiers))
    with pytest.raises(CompilationProblem, match="limitation.*source"):
        compile_report("timeline", materials=(material(), material(2)), generator=AnswerService(answer))


@pytest.mark.parametrize("field", ["limitation", "evidence_notice", "verification_notice"])
def test_qualifications_count_toward_persisted_section_capacity(field):
    huge = "Synthetic qualification. " * 3_000
    answer = replace(qualified_answer(), **{field: VerifiedClaim(huge, ()) if field == "limitation" else huge})
    with pytest.raises(CompilationProblem, match="too long to save"):
        compile_report("timeline", materials=(material(transcript=field == "evidence_notice"), material(2)), generator=AnswerService(answer))


def test_real_generation_transcript_warning_survives_compilation():
    class SourceEchoClient:
        available = True

        def generate(self, *, question, evidence, **kwargs):
            return {"answerable": True, "claims": [{"text": "The machine transcript appears to say that a synthetic delivery was mentioned.", "evidence_ids": ["S1"]}],
                    "limitation": None, "missing_information": ""}

    draft = compile_report("timeline", materials=(material(transcript=True),),
                           generator=GroundedGenerationService(SourceEchoClient()))
    assert "Evidence notice: " + MEDIA_TRANSCRIPT_NOTICE in draft.sections[0]["body"]


@pytest.mark.parametrize("sourced_limitation", [False, True])
def test_real_verifier_notice_remains_uncited_beside_sourced_limitation(tmp_path, sourced_limitation):
    first = material()
    first = replace(first, text="A synthetic delivery was recorded.",
                    citations=({**first.citations[0], "excerpt": "A synthetic delivery was recorded."},))
    selected = (first, material(2))
    omission_notice = "Some generated statements were omitted because their source support could not be verified."

    class PartlySupportedClient:
        available = True

        def generate(self, *, evidence, **kwargs):
            return {"answerable": True, "claims": [
                {"text": evidence[0].excerpt, "evidence_ids": ["S1"]},
                {"text": "An unsupported helicopter arrived at 99:99.", "evidence_ids": ["S1"]},
            ], "limitation": {"text": evidence[1].excerpt, "evidence_ids": ["S2"]} if sourced_limitation else None,
                "missing_information": ""}

    service = GroundedGenerationService(PartlySupportedClient())
    evidence = tuple(EvidenceItem(f"S{index}", item.title, "Line 1", item.citations[0]["excerpt"])
                     for index, item in enumerate(selected, 1))
    answer = service.answer("What is recorded about the synthetic delivery?", evidence)
    assert answer.omitted_claims == 1
    assert answer.verification_notice == omission_notice
    if sourced_limitation:
        assert answer.source_limitation == VerifiedClaim(selected[1].text, ("S2",))
        assert answer.limitation.text == selected[1].text + " " + omission_notice
    else:
        assert answer.source_limitation is None
        assert answer.limitation == VerifiedClaim(omission_notice, ())
    # Legacy conversation consumers retain their existing limitation and text.
    assert "Limitation: " + answer.limitation.text in answer.text

    draft = compile_report("timeline", materials=selected, generator=service,
                           budget=CompilationBudget(max_sections=1))
    finding = draft.sections[0]
    assert "Verification notice: " + omission_notice in finding["body"]
    assert finding["body"].count(omission_notice) == 1
    if sourced_limitation:
        assert "Limitation: " + selected[1].text + "\nLimitation source support: Source 2." in finding["body"]
        assert "Limitation: " + answer.limitation.text not in finding["body"]
    else:
        assert "Limitation:" not in finding["body"]
        assert "Limitation source support:" not in finding["body"]

    store = WorkspaceStore(tmp_path / "synthetic-verifier-notice.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler",
                                       preferred_principal_id="synthetic-compiler")
        matter_record = store.create_matter("Synthetic verifier notice", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter_record.matter_id, actor.principal_id,
            title=draft.title, purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        saved = store.report_sections(matter_record.matter_id, report.report_id)
        sections = tuple((section, store.report_citations(matter_record.matter_id, report.report_id, section.section_id))
                         for section in saved)
        assert saved[0].body == finding["body"]
        assert len(sections[0][1]) == (2 if sourced_limitation else 1)
        exported = export_report(matter_record, report, sections, "markdown").body.decode("utf-8")
        assert "Verification notice: " + omission_notice in exported
        assert exported.count(omission_notice) == 1
        if sourced_limitation:
            assert "Limitation: " + selected[1].text + "\nLimitation source support: Source 2." in exported
    finally:
        store.close()


@pytest.mark.parametrize("source_kind", ["transcript", "media_clip"])
@pytest.mark.parametrize("transcript_limitation", [False, True])
def test_mixed_source_notices_follow_section_support_through_export(tmp_path, source_kind, transcript_limitation):
    document_text = "The synthetic inspection occurred on 2024-04-02."
    transcript_text = "The machine transcript appears to say that a synthetic delivery was mentioned."
    first, second = material(), material(2, transcript=True)
    first = replace(first, text=document_text, citations=({**first.citations[0], "excerpt": document_text},))
    second = replace(second, text=transcript_text,
                     citations=({**second.citations[0], "kind": source_kind, "excerpt": transcript_text},))

    if source_kind == "media_clip":
        second = replace(second, citations=({**second.citations[0], "support_token": "",
            "media_clip_id": "media-clip-" + "2" * 32, "start_ms": 1_000, "end_ms": 2_000},))

    class MixedClient:
        available = True

        def generate(self, **kwargs):
            return {"answerable": True, "claims": [
                {"text": document_text, "evidence_ids": ["S1"]},
                {"text": transcript_text, "evidence_ids": ["S2"]},
            ], "limitation": {"text": transcript_text, "evidence_ids": ["S2"]} if transcript_limitation else None,
                "missing_information": ""}

    draft = compile_report("timeline", materials=(first, second), generator=GroundedGenerationService(MixedClient()))
    document = next(section for section in draft.sections if section["body"].startswith(document_text))
    transcript = next(section for section in draft.sections if section["body"].startswith(transcript_text))
    assert (MEDIA_TRANSCRIPT_NOTICE in document["body"]) == transcript_limitation
    assert MEDIA_TRANSCRIPT_NOTICE in transcript["body"]
    assert document["date_key"] == ("" if transcript_limitation else "2024-04-02")
    assert document["citations"] == ((first.citations[0], second.citations[0]) if transcript_limitation else first.citations)

    store = WorkspaceStore(tmp_path / "synthetic-mixed-notices.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler",
                                       preferred_principal_id="synthetic-compiler")
        matter_record = store.create_matter("Synthetic mixed evidence", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter_record.matter_id, actor.principal_id,
            title=draft.title, purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        saved = store.report_sections(matter_record.matter_id, report.report_id)
        saved_document = next(section for section in saved if section.body.startswith(document_text))
        assert saved_document.body == document["body"]
        sections = tuple((section, store.report_citations(matter_record.matter_id, report.report_id, section.section_id))
                         for section in saved)
        exported = export_report(matter_record, report, sections, "markdown").body.decode("utf-8")
        assert exported.count(MEDIA_TRANSCRIPT_NOTICE) == (2 if transcript_limitation else 1)
    finally:
        store.close()
