from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, TypeVar

from .contracts import (
    AvailabilityState,
    ContentOperation,
    LocatorMetadata,
    Matter,
    MatterState,
    Representation,
    RetrievalResult,
    RetrievalRun,
    Segment,
    SourceLocator,
    SourceReference,
    SourceVersion,
)


class AuthorizationError(PermissionError):
    pass


_T = TypeVar("_T")


class MatterStateRegistry:
    """Authoritative in-memory state fence for every matter operation."""

    def __init__(self, matters: Iterable[Matter]) -> None:
        self._matters = {matter.matter_id: matter for matter in matters}
        self._fence_callbacks: list[Callable[[str], None]] = []
        self._lock = threading.RLock()

    def register_fence_callback(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if callback not in self._fence_callbacks:
                self._fence_callbacks.append(callback)

    def matter(self, matter_id: str) -> Matter:
        with self._lock:
            try:
                return self._matters[matter_id]
            except KeyError as exc:
                raise AuthorizationError("unknown matter") from exc

    def perform_active(
        self,
        matter_id: str,
        operation: ContentOperation,
        action: Callable[[], _T],
    ) -> _T:
        """Check and execute under the same lock used by lifecycle fencing."""
        with self._lock:
            matter = self._matters.get(matter_id)
            if matter is None:
                raise AuthorizationError("unknown matter")
            if matter.state is not MatterState.ACTIVE:
                raise AuthorizationError(
                    f"{operation.value} denied for non-active matter"
                )
            return action()

    def require_active(self, matter_id: str, operation: ContentOperation) -> None:
        self.perform_active(matter_id, operation, lambda: None)

    def begin_closure(self, matter_id: str, closure_run_id: str) -> Matter:
        with self._lock:
            current = self._matters.get(matter_id)
            if current is None:
                raise AuthorizationError("unknown matter")
            if current.state is not MatterState.ACTIVE:
                raise ValueError("matter already has a closure lifecycle")
            closing = Matter.model_validate(
                current.model_dump()
                | {
                    "state": MatterState.CLOSING,
                    "active_closure_run_id": closure_run_id,
                }
            )
            self._matters[matter_id] = closing
            # Callbacks run while the state lock is held. Ticket operations acquire
            # locks in this same state-then-ticket order, so no ticket can be minted
            # between the fence and revocation.
            for callback in self._fence_callbacks:
                callback(matter_id)
            return closing

    def cancel_closure(self, matter_id: str, closure_run_id: str) -> Matter:
        with self._lock:
            current = self._matters.get(matter_id)
            if (
                current is None
                or current.state is not MatterState.CLOSING
                or current.active_closure_run_id != closure_run_id
            ):
                raise ValueError("matter is not in this closure run")
            active = Matter.model_validate(
                current.model_dump()
                | {"state": MatterState.ACTIVE, "active_closure_run_id": None}
            )
            self._matters[matter_id] = active
            return active

    def complete_closure(self, matter_id: str, closure_run_id: str) -> Matter:
        with self._lock:
            current = self._matters.get(matter_id)
            if (
                current is None
                or current.state is not MatterState.CLOSING
                or current.active_closure_run_id != closure_run_id
            ):
                raise ValueError("matter is not in this closure run")
            closed = Matter.model_validate(
                current.model_dump()
                | {"state": MatterState.CLOSED, "active_closure_run_id": None}
            )
            self._matters[matter_id] = closed
            return closed


class ReferenceResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    INVALID_REFERENCE = "invalid_reference"
    VERSION_MISMATCH = "version_mismatch"


@dataclass(frozen=True)
class ReferenceResolution:
    status: ReferenceResolutionStatus
    source: SourceVersion | None = None


class MatterAccess:
    def __init__(self, grants: dict[str, set[str]]) -> None:
        self._grants = {
            actor: frozenset(matters) for actor, matters in grants.items()
        }

    def require(self, actor_id: str, matter_id: str) -> None:
        if (
            not actor_id
            or not matter_id
            or matter_id not in self._grants.get(actor_id, ())
        ):
            raise AuthorizationError("matter is not authorized")


@dataclass(frozen=True)
class SearchHit:
    matter_id: str
    source_version_id: str
    text: str


class Catalog:
    def __init__(
        self,
        registry: MatterStateRegistry,
        sources: Iterable[SourceVersion],
        search_hits: Iterable[SearchHit] = (),
    ) -> None:
        self._registry = registry
        self._sources: dict[tuple[str, str], SourceVersion] = {}
        for item in sources:
            key = (item.matter_id, item.source_version_id)
            existing = self._sources.get(key)
            if existing is not None and existing != item:
                raise ValueError("conflicting source-version identity")
            self._sources[key] = item
        unique_hits: dict[tuple[str, str], SearchHit] = {}
        for hit in search_hits:
            key = (hit.matter_id, hit.source_version_id)
            existing = unique_hits.get(key)
            if existing is not None and existing != hit:
                raise ValueError("conflicting search-hit identity")
            if self._sources and key not in self._sources:
                raise ValueError("search hit identifies an unknown source version")
            unique_hits[key] = hit
        self._hits = tuple(unique_hits.values())
        self.lookup_count = 0

    @classmethod
    def from_fixture(cls, fixture: dict) -> "Catalog":
        matters = [
            Matter(
                matter_id=item["matter_id"],
                display_name=item["display_name"],
                state=MatterState.ACTIVE,
            )
            for item in fixture["matters"]
        ]
        hits = [
            SearchHit(
                item["matter_id"],
                source["source_version_id"],
                source["searchable_text"],
            )
            for item in fixture["matters"]
            for source in item["sources"]
        ]
        return cls(MatterStateRegistry(matters), (), hits)

    @property
    def state_registry(self) -> MatterStateRegistry:
        return self._registry

    def source_for_actor(
        self,
        access: MatterAccess,
        actor_id: str,
        matter_id: str,
        source_version_id: str,
    ) -> SourceVersion:
        access.require(actor_id, matter_id)

        def lookup() -> SourceVersion:
            self.lookup_count += 1
            return self._sources[(matter_id, source_version_id)]

        return self._registry.perform_active(
            matter_id, ContentOperation.RESOLVE_SOURCE, lookup
        )

    def search(
        self, access: MatterAccess, actor_id: str, matter_id: str, query: str
    ) -> list[SearchHit]:
        access.require(actor_id, matter_id)

        def retrieve() -> list[SearchHit]:
            words = query.casefold().split()
            return [
                hit
                for hit in self._hits
                if hit.matter_id == matter_id
                and all(word in hit.text.casefold() for word in words)
            ]

        return self._registry.perform_active(
            matter_id, ContentOperation.RETRIEVE, retrieve
        )

    @staticmethod
    def cache_key(matter_id: str, query: str) -> str:
        return f"{matter_id}:{hashlib.sha256(query.encode()).hexdigest()}"


def guard_content_operation(
    registry: MatterStateRegistry, matter_id: str, operation: ContentOperation
) -> None:
    registry.require_active(matter_id, operation)


def validate_retrieval_results(
    run: RetrievalRun, results: Iterable[RetrievalResult]
) -> tuple[RetrievalResult, ...]:
    materialized = tuple(results)
    if any(
        result.run_id != run.run_id
        or result.matter_id != run.matter_id
        or result.reference.matter_id != run.matter_id
        for result in materialized
    ):
        raise AuthorizationError("mixed retrieval result set")
    return materialized


def resolve_reference(
    registry: MatterStateRegistry,
    authorized_matter_id: str,
    reference: SourceReference,
    source: SourceVersion,
    *,
    representation: Representation | None = None,
    segment: Segment | None = None,
    excerpt_sha256: str | None = None,
) -> ReferenceResolution:
    registry.require_active(authorized_matter_id, ContentOperation.RESOLVE_SOURCE)
    if (
        reference.matter_id != authorized_matter_id
        or source.matter_id != authorized_matter_id
    ):
        return ReferenceResolution(ReferenceResolutionStatus.UNAUTHORIZED)
    if reference.source_version_id != source.source_version_id:
        return ReferenceResolution(ReferenceResolutionStatus.VERSION_MISMATCH)
    if source.availability is AvailabilityState.STALE:
        return ReferenceResolution(ReferenceResolutionStatus.STALE)
    if source.availability is not AvailabilityState.AVAILABLE:
        return ReferenceResolution(ReferenceResolutionStatus.UNAVAILABLE)
    locator = reference.locator
    if not _locator_within(source.locator_metadata, locator):
        return ReferenceResolution(ReferenceResolutionStatus.INVALID_REFERENCE)
    if locator.representation_id is not None:
        if representation is None or (
            representation.representation_id != locator.representation_id
            or representation.matter_id != authorized_matter_id
            or representation.source_version_id != source.source_version_id
            or representation.representation_id
            not in source.locator_metadata.representation_ids
            or not _locator_within(representation.locator_metadata, locator)
        ):
            return ReferenceResolution(ReferenceResolutionStatus.INVALID_REFERENCE)
    if locator.segment_id is not None:
        if segment is None or representation is None or (
            segment.segment_id != locator.segment_id
            or segment.matter_id != authorized_matter_id
            or segment.source_version_id != source.source_version_id
            or segment.representation_id != representation.representation_id
            or segment.segment_id not in representation.locator_metadata.segment_ids
            or not _locator_within(segment.locator_metadata, locator)
        ):
            return ReferenceResolution(ReferenceResolutionStatus.INVALID_REFERENCE)
    expected = locator.excerpt_sha256
    if expected is not None and expected != excerpt_sha256:
        return ReferenceResolution(ReferenceResolutionStatus.INVALID_REFERENCE)
    return ReferenceResolution(ReferenceResolutionStatus.RESOLVED, source)


def _locator_within(metadata: LocatorMetadata, locator: SourceLocator) -> bool:
    """Validate every requested form; absent metadata means inapplicable."""
    pages = metadata.pages
    page_by_number = {item.page: item for item in pages}
    page_by_printed = {
        item.printed_page: item for item in pages if item.printed_page is not None
    }
    page_by_bates = {item.bates: item for item in pages if item.bates is not None}

    anchors = []
    if locator.page is not None:
        anchor = page_by_number.get(locator.page)
        if anchor is None:
            return False
        anchors.append(anchor)
    if locator.printed_page is not None:
        anchor = page_by_printed.get(locator.printed_page)
        if anchor is None:
            return False
        anchors.append(anchor)
    if locator.bates_start is not None:
        anchor = page_by_bates.get(locator.bates_start)
        if anchor is None:
            return False
        anchors.append(anchor)
        if locator.bates_end is not None:
            end = page_by_bates.get(locator.bates_end)
            if end is None or pages.index(end) <= pages.index(anchor):
                return False
    if anchors and any(anchor != anchors[0] for anchor in anchors[1:]):
        return False

    if locator.timestamp_start_ms is not None:
        if (
            metadata.duration_ms is None
            or locator.timestamp_start_ms >= metadata.duration_ms
            or (
                locator.timestamp_end_ms is not None
                and locator.timestamp_end_ms > metadata.duration_ms
            )
        ):
            return False
    if locator.image_region is not None and metadata.image_width_px is None:
        return False
    if locator.character_start is not None:
        if (
            metadata.character_count is None
            or locator.character_start >= metadata.character_count
            or (
                locator.character_end is not None
                and locator.character_end > metadata.character_count
            )
        ):
            return False
    if locator.line_start is not None:
        if (
            metadata.line_count is None
            or locator.line_start > metadata.line_count
            or (
                locator.line_end is not None
                and locator.line_end > metadata.line_count
            )
        ):
            return False
    return True
