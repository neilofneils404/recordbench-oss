"""Portable, matter-scoped work-product exports generated entirely in memory."""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as xml_escape
from typing import Mapping, Sequence

from .branding import PRODUCT_NAME
from .workspace_store import (
    ConversationRecord,
    MatterRecord,
    MessageRecord,
    NotebookItemRecord,
    NotebookReferenceRecord,
    ReportCitationRecord,
    ReportRecord,
    ReportSectionRecord,
    ResearchJobRecord,
    ReviewCriterionRecord,
    ReviewCriterionVersionRecord,
    ReviewDecisionRecord,
    ReviewRunRecord,
)

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
ZIP_MEDIA_TYPE = "application/zip"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
JSON_MEDIA_TYPE = "application/json; charset=utf-8"
MAX_EXPORT_TEXT_CHARS = 10_000_000
MAX_WORKFLOW_EXPORT_BYTES = 100 * 1024 * 1024
MAX_READABLE_REVIEW_DECISIONS = 500


class ExportProblem(ValueError):
    """A bounded export problem safe to show to an authorized staff member."""


@dataclass(frozen=True)
class ExportArtifact:
    body: bytes
    media_type: str
    filename: str


@dataclass(frozen=True)
class ExportBlock:
    text: str
    style: str = "normal"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_file_stem(value: str, fallback: str = "recordbench-export") -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode(
        "ascii", errors="ignore"
    ).decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-.")[:90]
    if not stem or stem.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }:
        stem = fallback
    return stem


def _plain(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "\n".join(line.rstrip() for line in value.replace("\r", "").split("\n")).strip()


def _citations(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source = _plain(item.get("source_name"))
        location = _plain(item.get("location"))
        if source and location:
            result.append(f"{source} — {location}")
        elif source:
            result.append(source)
    return tuple(result)


def _answer_blocks(message: MessageRecord) -> list[ExportBlock]:
    payload = message.payload
    kind = payload.get("kind")
    blocks: list[ExportBlock] = []
    source_coverage = payload.get("source_coverage")
    if (
        isinstance(source_coverage, Mapping)
        and source_coverage.get("mode") == "partial"
    ):
        coverage_notice = _plain(source_coverage.get("notice"))
        if coverage_notice:
            blocks.append(ExportBlock(f"Source coverage: {coverage_notice}", "note"))
    review_scope = payload.get("review_scope")
    if isinstance(review_scope, Mapping):
        scope_notice = _plain(review_scope.get("notice"))
        if scope_notice:
            prefix = (
                "Completeness caution"
                if review_scope.get("collection_wide_request") is True
                else "Answer basis"
            )
            blocks.append(ExportBlock(f"{prefix}: {scope_notice}", "note"))
    if kind == "generated":
        introduction = _plain(payload.get("introduction"))
        if introduction:
            blocks.append(ExportBlock(introduction))
        evidence_notice = _plain(payload.get("evidence_notice"))
        if evidence_notice:
            blocks.append(ExportBlock(evidence_notice, "note"))
        claims = payload.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                if not isinstance(claim, Mapping):
                    continue
                text = _plain(claim.get("text"))
                if text:
                    blocks.append(ExportBlock(text, "bullet"))
                for citation in _citations(claim.get("citations")):
                    blocks.append(ExportBlock(f"Source: {citation}", "citation"))
        limitation = payload.get("limitation")
        if isinstance(limitation, Mapping):
            text = _plain(limitation.get("text"))
            if text:
                blocks.append(ExportBlock(f"Limitation: {text}", "note"))
            for citation in _citations(limitation.get("citations")):
                blocks.append(ExportBlock(f"Source: {citation}", "citation"))
    elif kind == "not-supported":
        text = _plain(payload.get("missing_information")) or message.content
        blocks.append(ExportBlock(text, "note"))
        for citation in _citations(payload.get("source_matches")):
            blocks.append(ExportBlock(f"Related source passage: {citation}", "citation"))
    else:
        blocks.append(ExportBlock(message.content, "note"))
    if not blocks:
        blocks.append(ExportBlock(message.content))
    return blocks


def answer_blocks(
    matter: MatterRecord,
    conversation: ConversationRecord,
    answer: MessageRecord,
    question: MessageRecord | None = None,
    *,
    exported_at: str | None = None,
) -> tuple[ExportBlock, ...]:
    if answer.role != "assistant" or answer.conversation_id != conversation.conversation_id:
        raise ExportProblem("That saved item is not an assistant answer in this conversation.")
    blocks = [
        ExportBlock(matter.display_name, "title"),
        ExportBlock(conversation.title, "subtitle"),
        ExportBlock(f"Exported from {PRODUCT_NAME} at {exported_at or _now()}.", "metadata"),
    ]
    if question is not None:
        blocks.extend(
            (
                ExportBlock("Question", "heading1"),
                ExportBlock(question.content),
            )
        )
    blocks.append(ExportBlock(f"{PRODUCT_NAME} answer", "heading1"))
    blocks.extend(_answer_blocks(answer))
    blocks.append(
        ExportBlock(
            "Review this work product against the cited source material before relying on it.",
            "footer",
        )
    )
    return tuple(blocks)


def conversation_blocks(
    matter: MatterRecord,
    conversation: ConversationRecord,
    messages: Sequence[MessageRecord],
    *,
    exported_at: str | None = None,
) -> tuple[ExportBlock, ...]:
    if any(message.conversation_id != conversation.conversation_id for message in messages):
        raise ExportProblem("Conversation export crossed a matter boundary.")
    blocks = [
        ExportBlock(matter.display_name, "title"),
        ExportBlock(conversation.title, "subtitle"),
        ExportBlock(f"Exported from {PRODUCT_NAME} at {exported_at or _now()}.", "metadata"),
    ]
    question_number = 0
    answer_number = 0
    for message in messages:
        if message.role == "user":
            question_number += 1
            blocks.append(ExportBlock(f"Question {question_number}", "heading1"))
            blocks.append(ExportBlock(message.content))
        else:
            answer_number += 1
            blocks.append(
                ExportBlock(f"{PRODUCT_NAME} answer {answer_number}", "heading1")
            )
            blocks.extend(_answer_blocks(message))
    if not messages:
        blocks.append(ExportBlock("This conversation does not contain any messages yet.", "note"))
    blocks.append(
        ExportBlock(
            "Review generated work product against the cited source material before relying on it.",
            "footer",
        )
    )
    return tuple(blocks)


def notebook_blocks(
    matter: MatterRecord,
    entries: Sequence[tuple[NotebookItemRecord, Sequence[NotebookReferenceRecord]]],
    *,
    exported_at: str | None = None,
    heading: str = "Matter notebook",
) -> tuple[ExportBlock, ...]:
    blocks = [
        ExportBlock(matter.display_name, "title"),
        ExportBlock(heading, "subtitle"),
        ExportBlock(f"Exported from {PRODUCT_NAME} at {exported_at or _now()}.", "metadata"),
    ]
    for index, (item, references) in enumerate(entries, 1):
        blocks.append(ExportBlock(f"{index}. {item.title}", "heading1"))
        blocks.append(
            ExportBlock(
                " · ".join(
                    value
                    for value in (
                        item.item_type.replace("_", " ").title(),
                        item.status.replace("_", " ").title(),
                        "Pinned" if item.is_pinned else "",
                    )
                    if value
                ),
                "metadata",
            )
        )
        if item.date_label:
            blocks.append(ExportBlock(f"Date: {item.date_label}"))
        if item.body:
            blocks.append(ExportBlock(item.body))
        blocks.append(
            ExportBlock(
                f"Created by {item.created_by_name or item.created_by} at {item.created_at}; "
                f"last updated by {item.updated_by_name or item.updated_by} at {item.updated_at}.",
                "metadata",
            )
        )
        for reference in references:
            blocks.append(
                ExportBlock(
                    f"Source: {reference.source_name} — {reference.location}",
                    "citation",
                )
            )
            blocks.append(ExportBlock(reference.excerpt, "citation"))
    if not entries:
        blocks.append(ExportBlock("No notebook items were present.", "note"))
    blocks.append(
        ExportBlock(
            "Suggested and disputed notebook items require review against their cited source material.",
            "footer",
        )
    )
    return tuple(blocks)


def _csv_safe(value: object) -> str:
    text = _plain(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def notebook_csv(
    entries: Sequence[tuple[NotebookItemRecord, Sequence[NotebookReferenceRecord]]]
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        (
            "Type", "Status", "Title", "Date", "Details", "Pinned", "Origin",
            "Created by", "Created at", "Updated by", "Updated at", "Sources",
        )
    )
    for item, references in entries:
        writer.writerow(
            (
                _csv_safe(item.item_type),
                _csv_safe(item.status),
                _csv_safe(item.title),
                _csv_safe(item.date_label),
                _csv_safe(item.body),
                "yes" if item.is_pinned else "no",
                _csv_safe(item.origin),
                _csv_safe(item.created_by_name or item.created_by),
                item.created_at,
                _csv_safe(item.updated_by_name or item.updated_by),
                item.updated_at,
                _csv_safe(
                    "; ".join(
                        f"{reference.source_name} — {reference.location}"
                        for reference in references
                    )
                ),
            )
        )
    encoded = ("\ufeff" + output.getvalue()).encode("utf-8")
    if len(encoded) > MAX_EXPORT_TEXT_CHARS:
        raise ExportProblem("This notebook is too large to export as one CSV file.")
    return encoded


def matter_report_blocks(
    matter: MatterRecord,
    conversations: Sequence[tuple[ConversationRecord, Sequence[MessageRecord]]],
    sources: Sequence[Mapping[str, object]],
    notebook_count: int = 0,
    transcript_count: int = 0,
    *,
    exported_at: str,
) -> tuple[ExportBlock, ...]:
    message_count = sum(len(messages) for _, messages in conversations)
    blocks = [
        ExportBlock(matter.display_name, "title"),
        ExportBlock("Matter work-product report", "subtitle"),
        ExportBlock(f"Exported from {PRODUCT_NAME} at {exported_at}.", "metadata"),
    ]
    if matter.descriptor:
        blocks.append(ExportBlock(matter.descriptor))
    blocks.extend(
        (
            ExportBlock("Bundle contents", "heading1"),
            ExportBlock(f"{len(conversations)} saved conversation(s)", "bullet"),
            ExportBlock(f"{message_count} saved message(s)", "bullet"),
            ExportBlock(f"{len(sources)} source inventory record(s)", "bullet"),
            ExportBlock(f"{notebook_count} matter notebook item(s)", "bullet"),
            ExportBlock(f"{transcript_count} reviewed transcript export(s)", "bullet"),
            ExportBlock(
                "Original source files are not included. This bundle contains work product and source references only.",
                "note",
            ),
            ExportBlock("Source inventory", "heading1"),
        )
    )
    if sources:
        for source in sources:
            label = _plain(source.get("name")) or "Unnamed source"
            kind = _plain(source.get("kind"))
            state = _plain(source.get("state"))
            count_label = _plain(source.get("count_label"))
            details = " · ".join(value for value in (kind, count_label, state) if value)
            blocks.append(ExportBlock(f"{label}{' — ' + details if details else ''}", "bullet"))
    else:
        blocks.append(ExportBlock("No source inventory records were present.", "note"))
    blocks.append(ExportBlock("Conversation index", "heading1"))
    for index, (conversation, messages) in enumerate(conversations, 1):
        blocks.append(
            ExportBlock(
                f"{index}. {conversation.title} — {len(messages)} message(s), last activity {conversation.updated_at}",
                "bullet",
            )
        )
    if not conversations:
        blocks.append(ExportBlock("No saved conversations were present.", "note"))
    return tuple(blocks)


def _markdown_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("*", "_", "[", "]", "<", ">", "#", "`", "|"):
        escaped = escaped.replace(character, "\\" + character)
    return escaped


def blocks_to_markdown(blocks: Sequence[ExportBlock]) -> bytes:
    parts: list[str] = []
    total = 0
    for block in blocks:
        value = _markdown_escape(block.text)
        total += len(value)
        if total > MAX_EXPORT_TEXT_CHARS:
            raise ExportProblem(
                "This export is too large to prepare at once. Export the conversations individually."
            )
        if block.style == "title":
            rendered = f"# {value}"
        elif block.style == "subtitle":
            rendered = f"## {value}"
        elif block.style == "heading1":
            rendered = f"### {value}"
        elif block.style == "bullet":
            rendered = f"- {value}"
        elif block.style in {"citation", "metadata", "footer"}:
            rendered = f"> {value.replace(chr(10), chr(10) + '> ')}"
        elif block.style == "note":
            rendered = f"**Note:** {value}"
        else:
            rendered = value
        parts.append(rendered)
    return ("\n\n".join(parts).rstrip() + "\n").encode("utf-8")


def _paragraph_xml(block: ExportBlock) -> str:
    style_map = {
        "title": "Title",
        "subtitle": "Subtitle",
        "heading1": "Heading1",
        "bullet": "ListBullet",
        "citation": "Citation",
        "note": "Note",
        "metadata": "Metadata",
        "footer": "Footer",
    }
    style = style_map.get(block.style, "Normal")
    runs: list[str] = []
    lines = block.text.split("\n") or [""]
    for index, line in enumerate(lines):
        if index:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(
            '<w:r><w:t xml:space="preserve">'
            + xml_escape(line, quote=False)
            + "</w:t></w:r>"
        )
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{"".join(runs)}</w:p>'


def blocks_to_docx(
    blocks: Sequence[ExportBlock], *, title: str, created_at: str
) -> bytes:
    total = sum(len(block.text) for block in blocks)
    if total > MAX_EXPORT_TEXT_CHARS:
        raise ExportProblem(
            "This export is too large to prepare at once. Export the conversations individually."
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        + "".join(_paragraph_xml(block) for block in blocks)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Subtitle"/><w:rPr><w:b/><w:color w:val="0A1630"/><w:sz w:val="38"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="46566E"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/></w:pPr><w:rPr><w:b/><w:color w:val="0A1630"/><w:sz w:val="27"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="420" w:hanging="240"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Citation"><w:name w:val="Citation"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="420"/><w:spacing w:after="80"/></w:pPr><w:rPr><w:color w:val="1C4A82"/><w:sz w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Note"><w:name w:val="Note"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:color w:val="6A554B"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Metadata"><w:name w:val="Metadata"/><w:basedOn w:val="Normal"/><w:rPr><w:color w:val="687487"/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="Footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="300"/></w:pPr><w:rPr><w:i/><w:color w:val="687487"/><w:sz w:val="18"/></w:rPr></w:style>
</w:styles>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
    package_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    core = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>{xml_escape(title, quote=False)}</dc:title><dc:creator>{PRODUCT_NAME}</dc:creator>
<dcterms:created xsi:type="dcterms:W3CDTF">{xml_escape(created_at, quote=False)}</dcterms:created>
</cp:coreProperties>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
    return output.getvalue()


def _artifact(
    blocks: Sequence[ExportBlock], *, stem: str, format_name: str, created_at: str
) -> ExportArtifact:
    if format_name == "markdown":
        return ExportArtifact(blocks_to_markdown(blocks), MARKDOWN_MEDIA_TYPE, stem + ".md")
    if format_name == "docx":
        return ExportArtifact(
            blocks_to_docx(blocks, title=blocks[0].text, created_at=created_at),
            DOCX_MEDIA_TYPE,
            stem + ".docx",
        )
    raise ExportProblem("Choose Word or Markdown for this export.")


def export_answer(
    matter: MatterRecord,
    conversation: ConversationRecord,
    answer: MessageRecord,
    question: MessageRecord | None,
    format_name: str,
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    created = exported_at or _now()
    blocks = answer_blocks(matter, conversation, answer, question, exported_at=created)
    stem = safe_file_stem(f"{matter.display_name}-{conversation.title}-answer")
    return _artifact(blocks, stem=stem, format_name=format_name, created_at=created)


def export_conversation(
    matter: MatterRecord,
    conversation: ConversationRecord,
    messages: Sequence[MessageRecord],
    format_name: str,
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    created = exported_at or _now()
    blocks = conversation_blocks(matter, conversation, messages, exported_at=created)
    stem = safe_file_stem(f"{matter.display_name}-{conversation.title}")
    return _artifact(blocks, stem=stem, format_name=format_name, created_at=created)


def export_notebook(
    matter: MatterRecord,
    entries: Sequence[tuple[NotebookItemRecord, Sequence[NotebookReferenceRecord]]],
    format_name: str,
    *,
    exported_at: str | None = None,
    heading: str = "Matter notebook",
    stem: str | None = None,
) -> ExportArtifact:
    created = exported_at or _now()
    filename_stem = safe_file_stem(stem or f"{matter.display_name}-notebook")
    if format_name == "csv":
        return ExportArtifact(notebook_csv(entries), CSV_MEDIA_TYPE, filename_stem + ".csv")
    blocks = notebook_blocks(matter, entries, exported_at=created, heading=heading)
    return _artifact(blocks, stem=filename_stem, format_name=format_name, created_at=created)


def export_report(
    matter: MatterRecord,
    report: ReportRecord,
    sections: Sequence[
        tuple[ReportSectionRecord, Sequence[ReportCitationRecord]]
    ],
    format_name: str,
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    created = exported_at or _now()
    blocks: list[ExportBlock] = [
        ExportBlock(report.title, "title"),
        ExportBlock(matter.display_name, "subtitle"),
        ExportBlock(
            f"{report.status.title()} work product exported from {PRODUCT_NAME} at {created}.",
            "metadata",
        ),
    ]
    if report.purpose:
        blocks.extend(
            (ExportBlock("Purpose", "heading1"), ExportBlock(report.purpose))
        )
    for index, (section, citations) in enumerate(sections, 1):
        blocks.append(ExportBlock(f"{index}. {section.heading}", "heading1"))
        if section.body:
            blocks.append(ExportBlock(section.body))
        for citation_index, citation in enumerate(citations, 1):
            blocks.append(
                ExportBlock(
                    f"Source {citation_index}: {citation.source_name} — {citation.location}",
                    "citation",
                )
            )
            if citation.excerpt:
                blocks.append(ExportBlock(citation.excerpt, "citation"))
            if citation.kind == "media_clip":
                blocks.append(
                    ExportBlock(
                        "Timestamped recording segment; export or play the saved clip in the matter to verify context.",
                        "note",
                    )
                )
    if not sections:
        blocks.append(ExportBlock("This report does not contain sections yet.", "note"))
    blocks.append(
        ExportBlock(
            "This is review work product. Verify every statement against the cited source material before relying on it.",
            "footer",
        )
    )
    stem = safe_file_stem(f"{matter.display_name}-{report.title}")
    return _artifact(tuple(blocks), stem=stem, format_name=format_name, created_at=created)


def export_research(
    matter: MatterRecord,
    job: ResearchJobRecord,
    format_name: str,
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    """Export one durable research run with its evidence and coverage ledger."""

    created = exported_at or _now()
    stem = safe_file_stem(f"{matter.display_name}-{job.title}-deep-research")
    result = dict(job.result)
    if format_name == "json":
        body = json.dumps(
            {
                "product": PRODUCT_NAME,
                "exported_at": created,
                "matter": {"id": matter.matter_id, "name": matter.display_name},
                "research": {
                    "id": job.job_id,
                    "title": job.title,
                    "question": job.question,
                    "state": job.state,
                    "created_at": job.created_at,
                    "finished_at": job.finished_at,
                    "plan": dict(job.plan),
                    "result": result,
                },
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        if len(body) > MAX_EXPORT_TEXT_CHARS:
            raise ExportProblem("This research run is too large to export as one JSON file.")
        return ExportArtifact(body, JSON_MEDIA_TYPE, stem + ".json")
    blocks: list[ExportBlock] = [
        ExportBlock(job.title, "title"),
        ExportBlock(matter.display_name, "subtitle"),
        ExportBlock(f"Deep Research exported from {PRODUCT_NAME} at {created}.", "metadata"),
        ExportBlock("Research question", "heading1"),
        ExportBlock(job.question),
    ]
    summary = _plain(result.get("summary"))
    if summary:
        blocks.extend((ExportBlock("Verified synthesis", "heading1"), ExportBlock(summary)))
    coverage = result.get("coverage")
    if isinstance(coverage, Mapping):
        blocks.append(ExportBlock("Coverage ledger", "heading1"))
        for label, key in (
            ("Search passes", "search_pass_count"),
            ("Candidate passages", "candidate_passage_count"),
            ("Evidence passages", "evidence_passage_count"),
            ("Distinct evidence sources", "evidence_source_count"),
        ):
            blocks.append(ExportBlock(f"{label}: {coverage.get(key, 0)}", "bullet"))
        notice = _plain(coverage.get("notice"))
        if notice:
            blocks.append(ExportBlock(notice, "note"))
    passes = result.get("passes")
    if isinstance(passes, list):
        blocks.append(ExportBlock("Research findings", "heading1"))
        for index, item in enumerate(passes, 1):
            if not isinstance(item, Mapping):
                continue
            blocks.append(ExportBlock(f"{index}. {_plain(item.get('query'))}", "heading1"))
            blocks.append(ExportBlock(_plain(item.get("text")) or "No supported finding.", "normal"))
    evidence = result.get("evidence")
    if isinstance(evidence, list):
        blocks.append(ExportBlock("Evidence ledger", "heading1"))
        for index, item in enumerate(evidence, 1):
            if not isinstance(item, Mapping):
                continue
            source = _plain(item.get("source_name"))
            location = _plain(item.get("location"))
            blocks.append(ExportBlock(f"{index}. {source} — {location}", "citation"))
            excerpt = _plain(item.get("excerpt"))
            if excerpt:
                blocks.append(ExportBlock(excerpt, "citation"))
    blocks.append(
        ExportBlock(
            "Deep Research is multi-pass retrieval work product, not a document-by-document completeness determination. Verify cited passages before relying on it.",
            "footer",
        )
    )
    return _artifact(tuple(blocks), stem=stem, format_name=format_name, created_at=created)


def export_full_review(
    matter: MatterRecord,
    criterion: ReviewCriterionRecord,
    version: ReviewCriterionVersionRecord,
    run: ReviewRunRecord,
    decisions: Sequence[ReviewDecisionRecord],
    metrics: Mapping[str, object],
    format_name: str,
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    """Export the frozen population, machine decisions, and human validation separately."""

    created = exported_at or _now()
    stem = safe_file_stem(f"{matter.display_name}-{criterion.title}-full-review")
    if format_name == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(
            (
                "Ordinal", "Source", "Type", "Machine decision", "Rationale",
                "Source locations", "Needs attention", "Validation sample",
                "Human decision", "Human note", "Reviewed by", "Reviewed at",
                "Source version", "Document id",
            )
        )
        for item in decisions:
            writer.writerow(
                (
                    item.ordinal,
                    _csv_safe(item.source_name),
                    _csv_safe(item.source_kind),
                    item.machine_decision,
                    _csv_safe(item.rationale),
                    _csv_safe(
                        "; ".join(
                            f"{citation.get('source_name', '')} — {citation.get('location', '')}"
                            for citation in item.citations
                        )
                    ),
                    _csv_safe(item.error_message),
                    "yes" if item.validation_sample else "no",
                    item.human_decision,
                    _csv_safe(item.human_note),
                    _csv_safe(item.reviewed_by or ""),
                    item.reviewed_at or "",
                    item.source_version_id,
                    item.document_id,
                )
            )
        body = ("\ufeff" + output.getvalue()).encode("utf-8")
        if len(body) > MAX_WORKFLOW_EXPORT_BYTES:
            raise ExportProblem("This review is too large to export as one CSV file.")
        return ExportArtifact(body, CSV_MEDIA_TYPE, stem + ".csv")
    if format_name == "json":
        body = json.dumps(
            {
                "product": PRODUCT_NAME,
                "exported_at": created,
                "matter": {"id": matter.matter_id, "name": matter.display_name},
                "criterion": {
                    "id": criterion.criterion_id,
                    "title": criterion.title,
                    "version_id": version.criterion_version_id,
                    "version": version.version_number,
                    "instructions": version.instructions,
                    "include_guidance": version.include_guidance,
                    "exclude_guidance": version.exclude_guidance,
                },
                "run": {
                    "id": run.run_id,
                    "kind": run.run_kind,
                    "state": run.state,
                    "snapshot_count": run.snapshot_count,
                    "reviewed_count": run.reviewed_count,
                    "included_count": run.included_count,
                    "excluded_count": run.excluded_count,
                    "attention_count": run.attention_count,
                    "created_at": run.created_at,
                    "finished_at": run.finished_at,
                },
                "validation_metrics": dict(metrics),
                "decisions": [
                    {
                        "ordinal": item.ordinal,
                        "document_id": item.document_id,
                        "source_version_id": item.source_version_id,
                        "source_name": item.source_name,
                        "source_kind": item.source_kind,
                        "machine_decision": item.machine_decision,
                        "rationale": item.rationale,
                        "citations": list(item.citations),
                        "error_message": item.error_message,
                        "validation_sample": bool(item.validation_sample),
                        "human_decision": item.human_decision,
                        "human_note": item.human_note,
                        "reviewed_by": item.reviewed_by,
                        "reviewed_at": item.reviewed_at,
                    }
                    for item in decisions
                ],
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        if len(body) > MAX_WORKFLOW_EXPORT_BYTES:
            raise ExportProblem("This review is too large to export as one JSON file.")
        return ExportArtifact(body, JSON_MEDIA_TYPE, stem + ".json")
    blocks: list[ExportBlock] = [
        ExportBlock(criterion.title, "title"),
        ExportBlock(matter.display_name, "subtitle"),
        ExportBlock(
            f"Full Review v{version.version_number} exported from {PRODUCT_NAME} at {created}.",
            "metadata",
        ),
        ExportBlock("Saved criterion", "heading1"),
        ExportBlock(version.instructions),
        ExportBlock("Run totals", "heading1"),
        ExportBlock(f"Frozen searchable population: {run.snapshot_count:,}", "bullet"),
        ExportBlock(f"Included: {run.included_count:,}", "bullet"),
        ExportBlock(f"Not identified: {run.excluded_count:,}", "bullet"),
        ExportBlock(f"Needs attention: {run.attention_count:,}", "bullet"),
        ExportBlock("Human validation", "heading1"),
        ExportBlock(
            f"{metrics.get('reviewed_total', 0)} of {metrics.get('sample_total', 0)} sampled decisions reviewed.",
            "normal",
        ),
    ]
    for label, key in (
        ("Precision", "precision"), ("Recall", "recall"),
        ("Elusion", "elusion"), ("Richness", "richness"), ("Error rate", "error_rate"),
    ):
        value = metrics.get(key)
        blocks.append(
            ExportBlock(f"{label}: {'not yet defined' if value is None else f'{float(value):.1%}'}", "bullet")
        )
    blocks.append(ExportBlock("Source decisions", "heading1"))
    readable_decisions = decisions[:MAX_READABLE_REVIEW_DECISIONS]
    if len(decisions) > len(readable_decisions):
        blocks.append(
            ExportBlock(
                f"This readable summary includes the first {len(readable_decisions):,} of "
                f"{len(decisions):,} source decisions. Use the complete CSV or JSON export "
                "for the full every-source ledger.",
                "note",
            )
        )
    for item in readable_decisions:
        blocks.append(
            ExportBlock(
                f"{item.ordinal}. {item.source_name} — {item.machine_decision.replace('_', ' ').title()}",
                "heading1",
            )
        )
        if item.rationale:
            blocks.append(ExportBlock(item.rationale))
        if item.human_decision:
            blocks.append(
                ExportBlock(
                    f"Human validation: {item.human_decision.replace('_', ' ').title()}"
                    + (f" — {item.human_note}" if item.human_note else ""),
                    "note",
                )
            )
        for citation in item.citations:
            blocks.append(
                ExportBlock(
                    f"Source: {_plain(citation.get('source_name'))} — {_plain(citation.get('location'))}",
                    "citation",
                )
            )
    blocks.append(
        ExportBlock(
            "Machine decisions do not replace attorney or reviewer judgment. Preserve the criterion version, validate a representative sample, and verify source support.",
            "footer",
        )
    )
    return _artifact(tuple(blocks), stem=stem, format_name=format_name, created_at=created)


def _portable_message(message: MessageRecord) -> dict[str, object]:
    result: dict[str, object] = {
        "role": message.role,
        "created_at": message.created_at,
        "content": message.content,
    }
    if message.role == "assistant":
        payload = message.payload
        source_coverage = payload.get("source_coverage")
        portable_coverage: dict[str, object] = {}
        if isinstance(source_coverage, Mapping):
            portable_coverage = {
                "mode": "partial"
                if source_coverage.get("mode") == "partial"
                else "complete",
                "searchable_count": int(source_coverage.get("searchable_count") or 0),
                "total_count": int(source_coverage.get("total_count") or 0),
                "excluded_count": int(source_coverage.get("excluded_count") or 0),
                "notice": _plain(source_coverage.get("notice")),
            }
        review_scope = payload.get("review_scope")
        portable_scope: dict[str, object] = {}
        if isinstance(review_scope, Mapping):
            portable_scope = {
                "mode": "focused",
                "collection_wide_request": bool(
                    review_scope.get("collection_wide_request")
                ),
                "searchable_source_count": int(
                    review_scope.get("searchable_source_count") or 0
                ),
                "candidate_passage_count": int(
                    review_scope.get("candidate_passage_count") or 0
                ),
                "candidate_source_count": int(
                    review_scope.get("candidate_source_count") or 0
                ),
                "cited_passage_count": int(
                    review_scope.get("cited_passage_count") or 0
                ),
                "cited_source_count": int(
                    review_scope.get("cited_source_count") or 0
                ),
                "notice": _plain(review_scope.get("notice")),
            }
        result["answer"] = {
            "kind": payload.get("kind") if payload.get("kind") in {"generated", "not-supported", "error"} else "saved",
            "introduction": _plain(payload.get("introduction")),
            "claims": [
                {
                    "text": _plain(claim.get("text")),
                    "citations": list(_citations(claim.get("citations"))),
                }
                for claim in payload.get("claims", [])
                if isinstance(claim, Mapping)
            ]
            if isinstance(payload.get("claims"), list)
            else [],
            "limitation": _plain(payload.get("limitation", {}).get("text"))
            if isinstance(payload.get("limitation"), Mapping)
            else "",
            "missing_information": _plain(payload.get("missing_information")),
            "evidence_notice": _plain(payload.get("evidence_notice")),
            "source_matches": list(_citations(payload.get("source_matches"))),
            "source_coverage": portable_coverage,
            "review_scope": portable_scope,
        }
    return result


def export_matter_bundle(
    matter: MatterRecord,
    conversations: Sequence[tuple[ConversationRecord, Sequence[MessageRecord]]],
    sources: Sequence[Mapping[str, object]],
    notebook: Sequence[
        tuple[NotebookItemRecord, Sequence[NotebookReferenceRecord]]
    ] = (),
    media_work_product: Sequence[Mapping[str, object]] = (),
    additional_work_product: Sequence[Mapping[str, object]] = (),
    *,
    exported_at: str | None = None,
) -> ExportArtifact:
    created = exported_at or _now()
    report = matter_report_blocks(
        matter,
        conversations,
        sources,
        len(notebook),
        len(media_work_product),
        exported_at=created,
    )
    report_markdown = blocks_to_markdown(report)
    report_docx = blocks_to_docx(report, title=matter.display_name, created_at=created)
    conversation_files: list[dict[str, object]] = []
    portable_conversations: list[dict[str, object]] = []
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("matter-report.md", report_markdown)
        archive.writestr("matter-report.docx", report_docx)
        archive.writestr(
            "README.txt",
            (
                f"{PRODUCT_NAME} work-product bundle\n\n"
                "This package contains saved conversations, generated work product, "
                "and source inventory references. It does not contain original source files.\n"
                "Matter notebook exports include staff-authored and review-state work product.\n"
                "Transcript exports, available transcript overviews, and a clip inventory are "
                "included when media was reviewed; recording and clip bytes are not included.\n"
                "Transcript overviews are fallible orientation and are not findings about what occurred.\n"
                "Completed Deep Research and Full Review ledgers are included under research/ and full-review/.\n"
                "Verify generated statements against the cited records before relying on them.\n"
            ).encode("utf-8"),
        )
        used_names: set[str] = set()
        for index, (conversation, messages) in enumerate(conversations, 1):
            base = f"{index:03d}-{safe_file_stem(conversation.title, 'conversation')}"
            candidate = base
            suffix = 2
            while candidate.casefold() in used_names:
                candidate = f"{base}-{suffix}"
                suffix += 1
            used_names.add(candidate.casefold())
            blocks = conversation_blocks(
                matter, conversation, messages, exported_at=created
            )
            markdown_path = f"conversations/{candidate}.md"
            docx_path = f"conversations/{candidate}.docx"
            archive.writestr(markdown_path, blocks_to_markdown(blocks))
            archive.writestr(
                docx_path,
                blocks_to_docx(blocks, title=conversation.title, created_at=created),
            )
            conversation_files.append(
                {
                    "title": conversation.title,
                    "message_count": len(messages),
                    "updated_at": conversation.updated_at,
                    "markdown": markdown_path,
                    "docx": docx_path,
                }
            )
            portable_conversations.append(
                {
                    "title": conversation.title,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                    "messages": [_portable_message(message) for message in messages],
                }
            )
        notebook_report = notebook_blocks(
            matter, notebook, exported_at=created
        )
        archive.writestr("notebook/matter-notebook.md", blocks_to_markdown(notebook_report))
        archive.writestr(
            "notebook/matter-notebook.docx",
            blocks_to_docx(notebook_report, title="Matter notebook", created_at=created),
        )
        archive.writestr("notebook/matter-notebook.csv", notebook_csv(notebook))
        portable_notebook = [
            {
                "type": item.item_type,
                "status": item.status,
                "title": item.title,
                "details": item.body,
                "date": item.date_label,
                "pinned": bool(item.is_pinned),
                "origin": item.origin,
                "created_by": item.created_by_name or item.created_by,
                "created_at": item.created_at,
                "updated_by": item.updated_by_name or item.updated_by,
                "updated_at": item.updated_at,
                "sources": [
                    {
                        "name": reference.source_name,
                        "location": reference.location,
                        "excerpt": reference.excerpt,
                        "excerpt_digest": reference.excerpt_digest,
                    }
                    for reference in references
                ],
            }
            for item, references in notebook
        ]
        archive.writestr(
            "notebook/notebook.json",
            json.dumps(
                {"schema": "case-intelligence-notebook-v1", "items": portable_notebook},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        media_manifest: list[dict[str, object]] = []
        clip_inventory: list[dict[str, object]] = []
        summary_count = 0
        used_media_names: set[str] = set()
        for index, item in enumerate(media_work_product, 1):
            source_name = _plain(item.get("source_name")) or f"Recording {index}"
            base = f"{index:03d}-{safe_file_stem(source_name, 'recording')}"
            candidate = base
            suffix = 2
            while candidate.casefold() in used_media_names:
                candidate = f"{base}-{suffix}"
                suffix += 1
            used_media_names.add(candidate.casefold())
            paths: dict[str, str] = {}
            for format_name, extension in (("markdown", ".md"), ("srt", ".srt"), ("json", ".json")):
                body = item.get(format_name)
                if not isinstance(body, bytes):
                    raise ExportProblem("A transcript export could not be prepared safely.")
                path = f"transcripts/{candidate}{extension}"
                archive.writestr(path, body)
                paths[format_name] = path
            summary_path = ""
            summary_body = item.get("summary_markdown")
            if summary_body is not None:
                if not isinstance(summary_body, bytes):
                    raise ExportProblem("A transcript overview could not be prepared safely.")
                summary_path = f"transcript-overviews/{candidate}.md"
                archive.writestr(summary_path, summary_body)
                summary_count += 1
            summary_coverage = item.get("summary_coverage")
            if summary_coverage is not None and not isinstance(summary_coverage, Mapping):
                raise ExportProblem("Transcript overview coverage is invalid.")
            clips = item.get("clips")
            if not isinstance(clips, Sequence) or isinstance(clips, (str, bytes)):
                raise ExportProblem("A media clip inventory could not be prepared safely.")
            for clip in clips:
                if not isinstance(clip, Mapping):
                    raise ExportProblem("A media clip inventory could not be prepared safely.")
                clip_inventory.append(
                    {
                        "source": source_name,
                        "title": _plain(clip.get("title")),
                        "start": _plain(clip.get("start")),
                        "end": _plain(clip.get("end")),
                        "created_at": _plain(clip.get("created_at")),
                    }
                )
            media_manifest.append(
                {
                    "source_name": source_name,
                    "review_state": _plain(item.get("review_state")),
                    "segment_count": int(item.get("segment_count") or 0),
                    "exports": paths,
                    "overview": summary_path or None,
                    "overview_coverage": dict(summary_coverage) if summary_coverage else None,
                    "clip_count": len(clips),
                }
            )
        clip_output = io.StringIO(newline="")
        clip_writer = csv.DictWriter(
            clip_output,
            fieldnames=("source", "title", "start", "end", "created_at"),
            lineterminator="\r\n",
        )
        clip_writer.writeheader()
        for clip in clip_inventory:
            clip_writer.writerow({key: _csv_safe(value) for key, value in clip.items()})
        archive.writestr(
            "media/clip-inventory.csv",
            ("\ufeff" + clip_output.getvalue()).encode("utf-8"),
        )
        archive.writestr(
            "media/media-work-product.json",
            json.dumps(
                {
                    "schema": "case-intelligence-media-work-product-v2",
                    "original_media_included": False,
                    "overview_count": summary_count,
                    "transcripts": media_manifest,
                    "clips": clip_inventory,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        additional_manifest: list[dict[str, object]] = []
        seen_additional_paths: set[str] = set()
        for item in additional_work_product:
            path = str(item.get("path") or "")
            body = item.get("body")
            kind = _plain(item.get("kind"))
            if (
                not re.fullmatch(r"(?:research|full-review)/[A-Za-z0-9][A-Za-z0-9._/-]{0,240}", path)
                or ".." in path.split("/")
                or path.casefold() in seen_additional_paths
                or not isinstance(body, bytes)
            ):
                raise ExportProblem("Additional work product could not be packaged safely.")
            seen_additional_paths.add(path.casefold())
            archive.writestr(path, body)
            additional_manifest.append(
                {"kind": kind, "path": path, "bytes": len(body)}
            )
        manifest = {
            "schema": "case-intelligence-work-product-bundle-v1",
            "exported_at": created,
            "matter": {
                "name": matter.display_name,
                "description": matter.descriptor,
            },
            "original_source_files_included": False,
            "source_count": len(sources),
            "conversation_count": len(conversations),
            "notebook_count": len(notebook),
            "transcript_count": len(media_work_product),
            "transcript_overview_count": summary_count,
            "clip_count": len(clip_inventory),
            "additional_work_product_count": len(additional_manifest),
            "additional_work_product": additional_manifest,
            "conversations": conversation_files,
        }
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "conversations.json",
            json.dumps(
                {"schema": "case-intelligence-conversations-v1", "conversations": portable_conversations},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
    if output.tell() > 100 * 1024 * 1024:
        raise ExportProblem(
            "This bundle is too large to prepare at once. Export the conversations individually."
        )
    return ExportArtifact(
        output.getvalue(),
        ZIP_MEDIA_TYPE,
        safe_file_stem(f"{matter.display_name}-work-product") + ".zip",
    )
