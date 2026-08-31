from __future__ import annotations

import pytest

from case_intelligence.contracts import (
    Representation,
    Segment,
    SourceLocator,
    SourceReference,
)
from case_intelligence.isolation import (
    Catalog,
    MatterAccess,
    MatterStateRegistry,
    ReferenceResolutionStatus,
    SearchHit,
    resolve_reference,
)
from case_intelligence.projections import project_reference
from tests.support import ACTOR_ALPHA, ALPHA, BRAVO, matter, source


def reference(**locator_values: object) -> SourceReference:
    return SourceReference(
        reference_id="ref-b1",
        matter_id=ALPHA,
        source_version_id="version-alpha",
        locator=SourceLocator(**locator_values),
    )


def representation(
    *, matter_id: str = ALPHA, source_version_id: str = "version-alpha"
) -> Representation:
    return Representation(
        representation_id="rep-alpha",
        matter_id=matter_id,
        source_version_id=source_version_id,
        kind="page_text",
        processor_version="deterministic-v1",
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
            "segment_ids": ["segment-alpha"],
        },
    )


def segment(
    *, matter_id: str = ALPHA, source_version_id: str = "version-alpha"
) -> Segment:
    return Segment(
        segment_id="segment-alpha",
        matter_id=matter_id,
        source_version_id=source_version_id,
        representation_id="rep-alpha",
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
        },
    )


@pytest.mark.parametrize(
    "locator",
    [
        {"page": 2},
        {"printed_page": "A-2"},
        {"bates_start": "SYN0001", "bates_end": "SYN0002"},
        {"timestamp_start_ms": 900, "timestamp_end_ms": 1000},
        {"image_region": (0.1, 0.2, 0.8, 0.9)},
        {"character_start": 0, "character_end": 42},
        {"line_start": 1, "line_end": 4},
        {"representation_id": "rep-alpha"},
        {"representation_id": "rep-alpha", "segment_id": "segment-alpha"},
        {
            "representation_id": "rep-alpha",
            "segment_id": "segment-alpha",
            "page": 1,
            "character_start": 2,
            "character_end": 8,
        },
    ],
)
def test_valid_bounded_synthetic_locators_resolve(locator: dict[str, object]) -> None:
    ref = reference(**locator)
    rep = representation() if ref.locator.representation_id else None
    seg = segment() if ref.locator.segment_id else None
    result = resolve_reference(
        MatterStateRegistry([matter(ALPHA)]),
        ALPHA,
        ref,
        source(ALPHA, version_id="version-alpha"),
        representation=rep,
        segment=seg,
    )
    assert result.status is ReferenceResolutionStatus.RESOLVED


@pytest.mark.parametrize(
    "locator",
    [
        {"page": 999999999},
        {"printed_page": "A-999"},
        {"bates_start": "SYN9999"},
        {"timestamp_start_ms": 1001},
        {"timestamp_start_ms": 900, "timestamp_end_ms": 1001},
        {"character_start": 42},
        {"character_start": 0, "character_end": 43},
        {"line_start": 5},
        {"line_start": 1, "line_end": 5},
        {"page": 1, "printed_page": "A-2"},
        {"page": 2, "bates_start": "SYN0001"},
    ],
)
def test_impossible_locator_bounds_are_rejected(locator: dict[str, object]) -> None:
    result = resolve_reference(
        MatterStateRegistry([matter(ALPHA)]),
        ALPHA,
        reference(**locator),
        source(ALPHA, version_id="version-alpha"),
    )
    assert result.status is ReferenceResolutionStatus.INVALID_REFERENCE
    assert result.source is None


def test_locator_form_must_be_applicable_to_source_modality() -> None:
    original = source(ALPHA, version_id="version-alpha")
    audio = original.__class__.model_validate(
        original.model_dump()
        | {
            "locator_metadata": {
                "duration_ms": 1000,
                "representation_ids": ["rep-alpha"],
            }
        }
    )
    assert (
        resolve_reference(
            MatterStateRegistry([matter(ALPHA)]),
            ALPHA,
            reference(page=1),
            audio,
        ).status
        is ReferenceResolutionStatus.INVALID_REFERENCE
    )
    assert (
        resolve_reference(
            MatterStateRegistry([matter(ALPHA)]),
            ALPHA,
            reference(timestamp_start_ms=500),
            audio,
        ).status
        is ReferenceResolutionStatus.RESOLVED
    )


def test_foreign_or_unregistered_representation_and_segment_are_rejected() -> None:
    registry = MatterStateRegistry([matter(ALPHA), matter(BRAVO)])
    ref = reference(representation_id="rep-alpha", segment_id="segment-alpha")
    foreign_rep = representation(matter_id=BRAVO)
    foreign_segment = segment(matter_id=BRAVO)
    assert (
        resolve_reference(
            registry,
            ALPHA,
            ref,
            source(ALPHA, version_id="version-alpha"),
            representation=foreign_rep,
            segment=foreign_segment,
        ).status
        is ReferenceResolutionStatus.INVALID_REFERENCE
    )
    unregistered = representation().model_copy(
        update={"representation_id": "rep-not-declared"}
    )
    assert (
        resolve_reference(
            registry,
            ALPHA,
            reference(representation_id="rep-not-declared"),
            source(ALPHA, version_id="version-alpha"),
            representation=unregistered,
        ).status
        is ReferenceResolutionStatus.INVALID_REFERENCE
    )


def test_catalog_rejects_conflicting_source_identity_and_dedupes_exact_duplicate() -> None:
    registry = MatterStateRegistry([matter(ALPHA)])
    original = source(ALPHA)
    catalog = Catalog(registry, [original, original])
    assert (
        catalog.source_for_actor(
            MatterAccess({ACTOR_ALPHA: {ALPHA}}),
            ACTOR_ALPHA,
            ALPHA,
            original.source_version_id,
        )
        == original
    )
    conflict = original.model_copy(update={"sha256": "b" * 64})
    with pytest.raises(ValueError, match="conflicting source-version identity"):
        Catalog(registry, [original, conflict])


def test_catalog_rejects_conflicting_duplicate_search_hit_identity() -> None:
    registry = MatterStateRegistry([matter(ALPHA)])
    with pytest.raises(ValueError, match="conflicting search-hit identity"):
        Catalog(
            registry,
            [source(ALPHA)],
            [
                SearchHit(ALPHA, "version-matter-alpha", "first text"),
                SearchHit(ALPHA, "version-matter-alpha", "different text"),
            ],
        )


def test_staff_projection_preserves_all_exact_navigation_without_diagnostics() -> None:
    item = source(ALPHA, version_id="version-alpha")
    projected = project_reference(
        item,
        reference(
            page=2,
            printed_page="A-2",
            bates_start="SYN0001",
            bates_end="SYN0002",
            timestamp_start_ms=100,
            timestamp_end_ms=200,
            image_region=(0.1, 0.2, 0.8, 0.9),
            character_start=2,
            character_end=8,
            line_start=1,
            line_end=3,
            representation_id="rep-alpha",
            segment_id="segment-alpha",
            excerpt_sha256="c" * 64,
        ),
    ).model_dump()
    assert projected == {
        "source_name": "Synthetic Report.txt",
        "page": 2,
        "printed_page": "A-2",
        "bates_start": "SYN0001",
        "bates_end": "SYN0002",
        "timestamp_start_ms": 100,
        "timestamp_end_ms": 200,
        "image_region": (0.1, 0.2, 0.8, 0.9),
        "character_start": 2,
        "character_end": 8,
        "line_start": 1,
        "line_end": 3,
        "representation_navigation_id": "rep-alpha",
        "segment_navigation_id": "segment-alpha",
    }
    assert not {
        "excerpt_sha256",
        "sha256",
        "relative_path",
        "linux_root",
        "unc_root",
        "score",
        "processor_version",
    } & projected.keys()
