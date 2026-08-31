from __future__ import annotations

from datetime import datetime, timezone

from case_intelligence.contracts import (
    AvailabilityState,
    LocationKind,
    Matter,
    MatterState,
    SourceLocation,
    SourceVersion,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
ALPHA = "matter-alpha"
BRAVO = "matter-bravo"
ACTOR_ALPHA = "actor-alpha"
ACTOR_BRAVO = "actor-bravo"


def matter(matter_id: str = ALPHA, state: MatterState = MatterState.ACTIVE) -> Matter:
    closure_run_id = f"closure-{matter_id}" if state is MatterState.CLOSING else None
    return Matter(matter_id=matter_id, display_name="Synthetic Matter", state=state, active_closure_run_id=closure_run_id)


def location(matter_id: str = ALPHA, kind: LocationKind = LocationKind.EVIDENCE_INPUT) -> SourceLocation:
    return SourceLocation(
        source_location_id=f"location-{matter_id}-{kind.value}",
        matter_id=matter_id,
        display_name="Synthetic source",
        kind=kind,
    )


def source(matter_id: str = ALPHA, *, version_id: str | None = None) -> SourceVersion:
    loc = location(matter_id)
    return SourceVersion(
        source_version_id=version_id or f"version-{matter_id}",
        matter_id=matter_id,
        source_location_id=loc.source_location_id,
        relative_path="reports/Synthetic Report.txt",
        display_name="Synthetic Report.txt",
        media_type="text/plain",
        byte_size=42,
        sha256="a" * 64,
        discovered_at=NOW,
        last_verified_at=NOW,
        availability=AvailabilityState.AVAILABLE,
        locator_metadata={
            "pages": [
                {"page": 1, "printed_page": "A-1", "bates": "SYN0001"},
                {"page": 2, "printed_page": "A-2", "bates": "SYN0002"},
            ],
            "duration_ms": 1000,
            "image_width_px": 100,
            "image_height_px": 80,
            "character_count": 42,
            "line_count": 4,
            "representation_ids": ["rep-alpha"],
        },
    )
