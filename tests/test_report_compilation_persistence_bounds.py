"""Synthetic transcript-date and persisted citation-capacity regressions."""
import pytest

from case_intelligence.generation import MEDIA_TRANSCRIPT_NOTICE, GroundedGenerationService
from case_intelligence.report_compilation import CompilationBudget, CompilationProblem, compile_report
from case_intelligence.workspace_store import WorkspaceStore
from case_intelligence.work_product_exports import export_report
from tests.test_report_compilation import citation, material, service


@pytest.mark.parametrize("source_kind", ["transcript", "media_clip"])
@pytest.mark.parametrize("mixed", [False, True])
def test_transcript_supported_dates_have_neutral_heading_and_sort_order(source_kind, mixed):
    statement = "The machine transcript appears to say that the synthetic delivery occurred on 2024-04-02."

    document_statement = "The synthetic review occurred on 2024-04-03."

    class TranscriptClient:
        available = True

        def generate(self, **kwargs):
            claims = [{"text": statement, "evidence_ids": ["S1"]}]
            if mixed:
                claims.append({"text": document_statement, "evidence_ids": ["S2"]})
            return {"answerable": True, "claims": claims, "limitation": None, "missing_information": ""}

    sources = ({**citation(text=statement), "kind": source_kind},)
    if mixed:
        sources += (citation(2, text=document_statement),)
    selected = (material(citations=sources),
                material(3, origin="human", citations=(), text="The synthetic review occurred on 2024-05-01."))
    draft = compile_report("timeline", materials=selected, generator=GroundedGenerationService(TranscriptClient()))
    assert draft.sections[0]["date_key"] == ("2024-04-03" if mixed else "2024-05-01")
    finding = next(section for section in draft.sections if section["body"].startswith(statement))
    assert finding["date_key"] == ""
    assert finding["heading"] == "Chronology — dates as stated"
    assert statement in finding["body"]
    assert MEDIA_TRANSCRIPT_NOTICE in finding["body"]


@pytest.mark.parametrize("source_kind", ["transcript", "media_clip"])
def test_offline_transcript_date_label_cannot_override_source_qualification(source_kind):
    item = material(text="The synthetic delivery occurred on 2024-04-02.", date_label="2024-04-02",
                    citations=({**citation(), "kind": source_kind},))
    draft = compile_report("timeline", materials=(item,))
    assert draft.sections[0]["date_key"] == ""
    assert "2024-04-02" not in draft.sections[0]["heading"]
    assert draft.sections[0]["citations"] == item.citations


@pytest.mark.parametrize("kind", ["timeline", "entities", "topic"])
@pytest.mark.parametrize("origin,status,category", [
    ("research", "verified", ""), ("human", "disputed", ""), ("human", "unreviewed", "gap"),
])
def test_excess_citations_are_rejected_before_model_work(kind, origin, status, category):
    class UnexpectedService:
        @property
        def available(self):
            pytest.fail("Citation count must be validated before consulting the model")

    item = material(origin=origin, review_status=status, category=category,
                    citations=tuple(citation(index) for index in range(1, 102)))
    with pytest.raises(CompilationProblem, match="100.*citation"):
        compile_report(kind, "delivery" if kind == "topic" else "", (item,), UnexpectedService())


@pytest.mark.parametrize("mode", ["offline_machine", "offline_human", "incomplete_model"])
def test_exact_citation_count_limit_persists_every_passage(tmp_path, mode):
    item = material(origin="human" if mode == "offline_human" else "research",
                    citations=tuple(citation(index, text=f"Synthetic delivery passage {index}.") for index in range(1, 101)))
    draft = compile_report("timeline", materials=(item,),
                           generator=service() if mode == "incomplete_model" else None,
                           budget=CompilationBudget(max_model_calls=1))
    finding = next(section for section in draft.sections if section["body"].startswith(item.text))
    assert finding["citations"] == item.citations
    if mode == "incomplete_model":
        assert item.material_id in draft.coverage["incompletely_analyzed_material_ids"]
    store = WorkspaceStore(tmp_path / "synthetic-citation-limit.sqlite")
    try:
        actor = store.upsert_principal("test", "synthetic-compiler", "Synthetic compiler", "synthetic-compiler",
                                       preferred_principal_id="synthetic-compiler")
        matter_record = store.create_matter("Synthetic citation limit", "Synthetic", actor.principal_id)
        report = store.create_report_from_sections(matter_record.matter_id, actor.principal_id,
            title=draft.title, purpose=draft.purpose, origin_id="synthetic-compilation", sections=draft.sections)
        saved = store.report_sections(matter_record.matter_id, report.report_id)
        stored_finding = next(section for section in saved if section.body == finding["body"])
        citations = store.report_citations(matter_record.matter_id, report.report_id, stored_finding.section_id)
        assert len(citations) == 100
        assert tuple(c.excerpt for c in citations) == tuple(c["excerpt"] for c in item.citations)
        sections = tuple((section, store.report_citations(matter_record.matter_id, report.report_id, section.section_id))
                         for section in saved)
        exported = export_report(matter_record, report, sections, "markdown").body.decode("utf-8")
        for citation_value in item.citations:
            assert citation_value["excerpt"] in exported
    finally:
        store.close()
