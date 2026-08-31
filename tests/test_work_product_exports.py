from __future__ import annotations

import io
import json
import zipfile
from xml.etree import ElementTree

from case_intelligence.work_product_exports import (
    DOCX_MEDIA_TYPE,
    export_answer,
    export_conversation,
    export_matter_bundle,
)
from case_intelligence.workspace_store import (
    ConversationRecord,
    MatterRecord,
    MessageRecord,
)


STAMP = "2026-08-27T15:00:00Z"


def _records():
    matter = MatterRecord(
        "ci-matter-" + "a" * 32,
        "m-" + "a" * 12,
        "Synthetic & <Matter>",
        "Generated fixture",
        "principal-owner",
        STAMP,
        STAMP,
    )
    conversation = ConversationRecord(
        "conversation-" + "b" * 32,
        matter.matter_id,
        "Loading dock timeline",
        STAMP,
        STAMP,
    )
    question = MessageRecord(
        "message-" + "c" * 32,
        conversation.conversation_id,
        1,
        "user",
        "What happened near the loading dock?",
        {},
        STAMP,
    )
    answer = MessageRecord(
        "message-" + "d" * 32,
        conversation.conversation_id,
        2,
        "assistant",
        "A supported answer.",
        {
            "kind": "generated",
            "introduction": "The supplied record supports one event.",
            "claims": [
                {
                    "text": "A vehicle arrived at 10:12 p.m.",
                    "citations": [
                        {
                            "source_name": "Generated report.pdf",
                            "location": "Page 2",
                            "href": "/internal/not-portable",
                        }
                    ],
                }
            ],
            "limitation": {
                "text": "The record does not identify the driver.",
                "citations": [],
            },
            "source_coverage": {
                "mode": "partial",
                "searchable_count": 10,
                "total_count": 11,
                "excluded_count": 1,
                "notice": (
                    "Search and answers use 10 of 11 sources. "
                    "1 source needs attention and is excluded."
                ),
            },
            "review_scope": {
                "mode": "focused",
                "collection_wide_request": True,
                "searchable_source_count": 10,
                "candidate_passage_count": 12,
                "candidate_source_count": 8,
                "cited_passage_count": 1,
                "cited_source_count": 1,
                "notice": (
                    "This is a focused answer from the highest-ranked passages, "
                    "not a document-by-document completeness review."
                ),
            },
        },
        STAMP,
    )
    return matter, conversation, question, answer


def test_answer_and_conversation_exports_are_readable_markdown_and_docx():
    matter, conversation, question, answer = _records()
    markdown = export_answer(
        matter,
        conversation,
        answer,
        question,
        "markdown",
        exported_at=STAMP,
    )
    assert markdown.media_type.startswith("text/markdown")
    text = markdown.body.decode()
    assert "Synthetic & \\<Matter\\>" in text
    assert "A vehicle arrived at 10:12 p.m." in text
    assert "Generated report.pdf — Page 2" in text
    assert "Search and answers use 10 of 11 sources" in text
    assert "Completeness caution" in text
    assert "not a document-by-document completeness review" in text
    assert "/internal/not-portable" not in text

    docx = export_conversation(
        matter,
        conversation,
        (question, answer),
        "docx",
        exported_at=STAMP,
    )
    assert docx.media_type == DOCX_MEDIA_TYPE
    with zipfile.ZipFile(io.BytesIO(docx.body)) as archive:
        assert archive.testzip() is None
        document = archive.read("word/document.xml")
        ElementTree.fromstring(document)
        rendered = document.decode()
        assert "Loading dock timeline" in rendered
        assert "Generated report.pdf — Page 2" in rendered
        assert "&lt;Matter&gt;" in rendered


def test_matter_bundle_has_portable_work_product_without_originals_or_internal_links():
    matter, conversation, question, answer = _records()
    artifact = export_matter_bundle(
        matter,
        ((conversation, (question, answer)),),
        (
            {
                "name": "Generated report.pdf",
                "kind": "PDF",
                "state": "Searchable",
                "count_label": "2 pages",
            },
        ),
        exported_at=STAMP,
    )
    with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
        names = set(archive.namelist())
        assert {
            "README.txt",
            "manifest.json",
            "conversations.json",
            "matter-report.md",
            "matter-report.docx",
        }.issubset(names)
        assert any(name.startswith("conversations/001-Loading-dock-timeline") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["original_source_files_included"] is False
        assert manifest["source_count"] == 1
        portable = archive.read("conversations.json").decode()
        assert "A vehicle arrived at 10:12 p.m." in portable
        assert '"excluded_count": 1' in portable
        assert '"collection_wide_request": true' in portable
        assert '"candidate_passage_count": 12' in portable
        assert "Search and answers use 10 of 11 sources" in portable
        assert "/internal/not-portable" not in portable
        assert matter.matter_id not in portable
        assert conversation.conversation_id not in portable
        assert "Original source files are not included" in archive.read(
            "matter-report.md"
        ).decode()
