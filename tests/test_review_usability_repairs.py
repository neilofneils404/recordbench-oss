from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from case_intelligence.review_bench_v2 import Candidate
from case_intelligence.workbench import CaseIntelligenceWorkbench, MatterRecord


ROOT = Path(__file__).parents[1]


def test_transcript_candidate_is_canonicalized_before_support_token():
    matter = MatterRecord(
        "matter-1", "synthetic-matter", "Synthetic matter", "", "actor-1", "now", "now"
    )
    candidate = Candidate(
        "matter-1",
        "document-1",
        "chunk-1",
        "Synthetic recording.wav",
        1,
        "Generated transcript passage.",
        line_start=0,
        line_end=2_000,
        source_version_id="version-1",
        excerpt_digest="digest-1",
    )
    workbench = object.__new__(CaseIntelligenceWorkbench)
    workbench.source_store = lambda _matter: SimpleNamespace(
        get=lambda _document_id: SimpleNamespace(media_type="audio/wav")
    )

    citation = workbench._citation(matter, candidate)

    assert citation.evidence_kind == "transcript"
    assert citation.support_token == workbench._support_token(
        replace(candidate, evidence_kind="transcript")
    )
    assert "play=1" in citation.href


def test_media_review_theme_and_independent_scroll_contract():
    styles = (
        ROOT / "src/case_intelligence/static/case-intelligence.css"
    ).read_text(encoding="utf-8")

    assert "max-height: calc(100vh - var(--topbar-height) - 28px)" in styles
    assert "overscroll-behavior: contain" in styles
    assert "--scrollbar-thumb-hover" in styles
    assert "color-scheme: dark" in styles
    assert ".speaker-review-panel {" in styles
    assert "background: var(--surface);" in styles
    assert ".media-summary-card, .playback-compatibility" in styles
