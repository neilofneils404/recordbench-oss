from __future__ import annotations

from .contracts import (
    SourceReference,
    SourceVersion,
    StaffReferenceProjection,
    StaffRetrievalProjection,
    StaffSourceProjection,
    TicketLaunchProjection,
)


def project_source(source: SourceVersion) -> StaffSourceProjection:
    return StaffSourceProjection(display_name=source.display_name, media_type=source.media_type, availability=source.availability)


def project_reference(source: SourceVersion, reference: SourceReference) -> StaffReferenceProjection:
    if source.matter_id != reference.matter_id or source.source_version_id != reference.source_version_id:
        raise ValueError("source/reference mismatch")
    locator = reference.locator
    return StaffReferenceProjection(
        source_name=source.display_name, page=locator.page, printed_page=locator.printed_page,
        bates_start=locator.bates_start, bates_end=locator.bates_end,
        timestamp_start_ms=locator.timestamp_start_ms, timestamp_end_ms=locator.timestamp_end_ms,
        image_region=locator.image_region,
        character_start=locator.character_start,
        character_end=locator.character_end,
        line_start=locator.line_start,
        line_end=locator.line_end,
        representation_navigation_id=locator.representation_id,
        segment_navigation_id=locator.segment_id,
    )


def project_retrieval(source: SourceVersion, reference: SourceReference) -> StaffRetrievalProjection:
    return StaffRetrievalProjection(source=project_source(source), support=project_reference(source, reference))


def project_ticket(ticket: TicketLaunchProjection) -> TicketLaunchProjection:
    return TicketLaunchProjection(uri=ticket.uri, expires_at=ticket.expires_at)
