from __future__ import annotations

from case_intelligence.review_bench_v2 import Candidate
from case_intelligence.review_quality import rank_exact_record_candidates


def _candidate(document_id: str, source_name: str, text: str) -> Candidate:
    return Candidate(
        "matter-quality",
        document_id,
        f"chunk-{document_id}",
        source_name,
        1,
        text,
        0.5,
        source_version_id="quality-v1",
        excerpt_digest=(document_id * 64)[:64],
    )


def test_exact_record_rescue_does_not_match_identifier_prefixes() -> None:
    requested_record = _candidate(
        "dispatch-note",
        "Generated dispatch note.txt",
        "Dispatch note EVT-4821 identifies the requested event.",
    )
    prefix_collision = _candidate(
        "event-log",
        "Access control event log.csv",
        "System event EVT-48210 | accepted | 08:42:17 | reader 4.",
    )

    ranked = rank_exact_record_candidates(
        "At what exact time did system event EVT-4821 occur?",
        (requested_record, prefix_collision),
        matter_id="matter-quality",
    )

    assert [item.document_id for item in ranked] == [
        "dispatch-note",
        "event-log",
    ]
