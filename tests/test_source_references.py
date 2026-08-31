import pytest
from pydantic import ValidationError

from case_intelligence.contracts import AvailabilityState, Representation, Segment, SourceLocator, SourceReference
from case_intelligence.isolation import MatterStateRegistry, ReferenceResolutionStatus, resolve_reference
from tests.support import ALPHA, BRAVO, matter, source


REGISTRY = MatterStateRegistry([matter(ALPHA), matter(BRAVO)])


def reference(**locator_values: object) -> SourceReference:
    return SourceReference(
        reference_id="ref-alpha",
        matter_id=ALPHA,
        source_version_id="version-alpha",
        locator=SourceLocator(**locator_values),
    )


@pytest.mark.parametrize("locator", [
    {"page": 1, "printed_page": "A-1"},
    {"bates_start": "SYN0001", "bates_end": "SYN0002"},
    {"timestamp_start_ms": 0, "timestamp_end_ms": 500},
    {"image_region": (0.1, 0.2, 0.8, 0.9)},
    {"character_start": 0, "character_end": 10},
    {"line_start": 1, "line_end": 3},
    {"representation_id": "rep-alpha", "segment_id": "segment-alpha"},
])
def test_exact_locator_forms_resolve(locator: dict[str, object]) -> None:
    ref = reference(**locator)
    representation = None
    segment = None
    if ref.locator.representation_id is not None:
        representation = Representation(
            representation_id="rep-alpha",
            matter_id=ALPHA,
            source_version_id="version-alpha",
            kind="page",
            processor_version="deterministic-v1",
            locator_metadata=source(ALPHA).locator_metadata.model_copy(
                update={"segment_ids": ("segment-alpha",)}
            ),
        )
    if ref.locator.segment_id is not None:
        segment = Segment(
            segment_id="segment-alpha",
            matter_id=ALPHA,
            source_version_id="version-alpha",
            representation_id="rep-alpha",
            locator_metadata=source(ALPHA).locator_metadata,
        )
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="version-alpha"), representation=representation, segment=segment).status is ReferenceResolutionStatus.RESOLVED


@pytest.mark.parametrize("locator", [{}, {"timestamp_end_ms": 4}, {"timestamp_start_ms": 4, "timestamp_end_ms": 4}, {"segment_id": "segment"}, {"image_region": (0, 0, 1.1, 1)}])
def test_invalid_locator_forms_fail(locator: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        reference(**locator)


def test_resolution_never_falls_back() -> None:
    ref = reference(page=1, excerpt_sha256="b" * 64)
    assert resolve_reference(REGISTRY, BRAVO, ref, source(ALPHA, version_id="version-alpha")).status is ReferenceResolutionStatus.UNAUTHORIZED
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="other")).status is ReferenceResolutionStatus.VERSION_MISMATCH
    stale = source(ALPHA, version_id="version-alpha").model_copy(update={"availability": AvailabilityState.STALE})
    assert resolve_reference(REGISTRY, ALPHA, ref, stale).status is ReferenceResolutionStatus.STALE
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="version-alpha"), excerpt_sha256="c" * 64).status is ReferenceResolutionStatus.INVALID_REFERENCE


def test_representation_and_segment_resolution_require_exact_bindings() -> None:
    ref = reference(representation_id="rep-alpha", segment_id="segment-alpha")
    representation = Representation(
        representation_id="rep-alpha",
        matter_id=ALPHA,
        source_version_id="version-alpha",
        kind="page",
        processor_version="deterministic-v1",
        locator_metadata=source(ALPHA).locator_metadata.model_copy(
            update={"segment_ids": ("segment-alpha",)}
        ),
    )
    segment = Segment(
        segment_id="segment-alpha",
        matter_id=ALPHA,
        source_version_id="version-alpha",
        representation_id="rep-alpha",
        locator_metadata=source(ALPHA).locator_metadata,
    )
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="version-alpha"), representation=representation, segment=segment).status is ReferenceResolutionStatus.RESOLVED
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="version-alpha")).status is ReferenceResolutionStatus.INVALID_REFERENCE
    foreign_segment = segment.model_copy(update={"matter_id": BRAVO})
    assert resolve_reference(REGISTRY, ALPHA, ref, source(ALPHA, version_id="version-alpha"), representation=representation, segment=foreign_segment).status is ReferenceResolutionStatus.INVALID_REFERENCE
