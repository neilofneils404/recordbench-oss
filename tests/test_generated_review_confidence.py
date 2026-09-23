"""Synthetic adversarial claims test presentation, not real-model accuracy."""
from __future__ import annotations

import io
import json
import zipfile
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import (
    EvidenceItem, GenerationGroundingRejected, GroundedGenerationService,
    VerifiedAnswer, VerifiedClaim,
)
from case_intelligence.workbench import create_workbench_app
from case_intelligence.work_product_exports import export_answer, export_conversation, export_matter_bundle
from case_intelligence.workspace_store import ConversationRecord, MatterRecord, MessageRecord


LEGACY_INTRODUCTION = "The searchable sources support this answer:"
INTRODUCTION = "Generated answer for source review:"
NOTICE = "Citations and automated checks do not establish that a claim is correct."
STAMP = "2026-09-22T12:00:00Z"


class SyntheticGenerator:
    available = True

    def __init__(self, claim):
        self.claim = claim

    def generate(self, **kwargs):
        return {
            "answerable": True,
            "claims": [{"text": self.claim, "evidence_ids": [item.evidence_id for item in kwargs["evidence"]]}],
            "limitation": None,
            "missing_information": "",
        }


@pytest.mark.parametrize("sources,claim", [
    (("The board approved project MARBLE-22 at the meeting.",),
     "The board rejected project MARBLE-22 at the meeting."),
    (("Harlow paid Denton for the warehouse delivery.",),
     "Denton paid Harlow for the warehouse delivery."),
    (("Reyes waited at the marina.", "The gun was found in the car."),
     "Reyes had the gun in the car at the marina."),
    (("The sample may possibly match the reference, pending confirmation.",),
     "The sample matches the reference."),
])
def test_meaning_changing_claim_is_rejected_or_presented_for_review(sources, claim):
    evidence = tuple(EvidenceItem(f"S{index}", f"Synthetic-{index}.txt", "Line 1", source)
                     for index, source in enumerate(sources, 1))
    try:
        answer = GroundedGenerationService(SyntheticGenerator(claim)).answer("What does the record say?", evidence)
    except GenerationGroundingRejected:
        # Future semantic safeguards may reject these; do not freeze false acceptance.
        return
    assert answer.introduction == INTRODUCTION
    assert answer.claims[0].evidence_ids == tuple(item.evidence_id for item in evidence)
    assert claim in answer.text


def test_faithful_paraphrase_remains_usable_and_fabrication_is_rejected():
    evidence = (EvidenceItem("S1", "Synthetic minutes.txt", "Line 1",
                             "The board approved project MARBLE-22 at the meeting."),)
    answer = GroundedGenerationService(SyntheticGenerator(
        "At the meeting, the board approved project MARBLE-22."
    )).answer("What did the board decide?", evidence)
    assert answer.answerable and answer.introduction == INTRODUCTION
    with pytest.raises(GenerationGroundingRejected):
        GroundedGenerationService(SyntheticGenerator(
            "A helicopter transported chemical samples to Denver."
        )).answer("What did the board decide?", evidence)


def _payload():
    return {"kind": "generated", "introduction": LEGACY_INTRODUCTION,
            "claims": [{"text": "The board rejected project MARBLE-22.", "citations": [
                {"source_name": "Synthetic minutes.txt", "location": "Line 1",
                 "href": "?support=" + "a" * 40, "support_token": "a" * 40}
            ]}], "limitation": None}


@pytest.mark.parametrize("format_name", ["markdown", "docx"])
def test_legacy_answer_and_conversation_exports_warn_without_rewriting_storage(format_name):
    matter = MatterRecord("matter-" + "a" * 32, "m-" + "a" * 12,
                          "Synthetic review", "Synthetic", "owner", STAMP, STAMP)
    conversation = ConversationRecord("conversation-" + "b" * 32, matter.matter_id,
                                      "Synthetic decision", STAMP, STAMP)
    historical = VerifiedAnswer(
        True, LEGACY_INTRODUCTION,
        (VerifiedClaim("The board rejected project MARBLE-22.", ("S1",)),),
        None, "", ("S1",), True, 1,
    )
    answer = MessageRecord("message-" + "c" * 32, conversation.conversation_id, 1,
                           "assistant", historical.text, _payload(), STAMP)
    for artifact in (
        export_answer(matter, conversation, answer, None, format_name, exported_at=STAMP),
        export_conversation(matter, conversation, (answer,), format_name, exported_at=STAMP),
    ):
        if format_name == "docx":
            with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                rendered = " ".join(root.itertext())
        else:
            rendered = artifact.body.decode()
        assert INTRODUCTION in rendered and NOTICE in rendered
        assert LEGACY_INTRODUCTION not in rendered
        assert "The board rejected project MARBLE-22." in rendered
        assert "Synthetic minutes.txt" in rendered and "Line 1" in rendered
    assert answer.payload == _payload()
    bundle = export_matter_bundle(matter, ((conversation, (answer,)),), (), exported_at=STAMP)
    with zipfile.ZipFile(io.BytesIO(bundle.body)) as archive:
        portable = json.loads(archive.read("conversations.json"))
        # Inspect the portable document actually shipped, not a helper return value.
        assert NOTICE in json.dumps(portable)
        assert INTRODUCTION in json.dumps(portable)
        assert LEGACY_INTRODUCTION not in json.dumps(portable)
        assert "Synthetic minutes.txt" in json.dumps(portable)
    assert answer.content == historical.text


def test_saved_answer_page_and_assistant_warn_without_mutating_history(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        created = client.post("/matters", data={"name": "Synthetic confidence", "descriptor": "Synthetic"},
                              follow_redirects=False)
        assert created.status_code == 303
        slug = created.headers["location"].split("/")[2]
        bench = app.state.workbench
        matter = bench.matter(slug, "development-taylor-morgan")
        conversation = bench.workspace.get_conversation(matter.matter_id)
        saved = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
                                               "assistant", "Synthetic historical claim.", _payload())
        for url in (f"/matters/{slug}", f"/matters/{slug}/assistant"):
            page = client.get(url)
            assert page.status_code == 200
            assert NOTICE in page.text and INTRODUCTION in page.text
            assert LEGACY_INTRODUCTION not in page.text
            assert "Verify claims and citations" not in page.text
            assert "Synthetic minutes.txt" in page.text
            assert "support=" + "a" * 40 in page.text
        current = next(message for message in bench.workspace.messages(matter.matter_id, conversation.conversation_id)
                       if message.message_id == saved.message_id)
        assert current.payload == _payload()
