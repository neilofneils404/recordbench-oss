from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore


ACTOR = "synthetic-reviewer"


class EvidenceEchoGenerator:
    available = True

    def generate(self, **kwargs):
        evidence = kwargs["evidence"]
        return {
            "answerable": bool(evidence),
            "claims": [
                {"text": item.excerpt[:600], "evidence_ids": [item.evidence_id]}
                for item in evidence[:1]
            ],
            "limitation": None,
            "missing_information": "",
        }


def _research_result() -> dict[str, object]:
    citation = {
        "source_name": "Synthetic source.txt",
        "location": "line 1",
        "excerpt": "A generated machine record places the event at 09:14.",
        "href": "/synthetic-support",
        "support_token": "a" * 40,
        "matter_id": "matter-placeholder",
        "document_id": "b" * 32,
        "source_version_id": "c" * 32,
        "excerpt_digest": "d" * 64,
        "chunk_id": "e" * 32,
        "unit_number": 1,
        "line_start": 1,
        "line_end": 1,
        "evidence_kind": "document",
    }
    return {
        "summary": "The generated record reports 09:14.",
        "answer": {
            "kind": "generated",
            "introduction": "The cited source supports this result.",
            "claims": [
                {
                    "text": "The generated record reports 09:14.",
                    "citations": [citation],
                }
            ],
            "limitation": None,
            "missing_information": "",
        },
        "evidence": [citation],
        "coverage": {
            "search_pass_count": 3,
            "evidence_source_count": 1,
            "notice": "Several focused searches were used; this did not check every source.",
        },
    }


def test_research_result_is_appended_once_to_its_conversation_and_survives_restart(
    tmp_path,
):
    path = tmp_path / "workbench.sqlite"
    store = WorkspaceStore(path)
    principal = store.upsert_principal(
        "test", ACTOR, "Synthetic Reviewer", ACTOR, preferred_principal_id=ACTOR
    )
    matter = store.create_matter(
        "Generated continuity matter", "Synthetic fixture", principal.principal_id
    )
    conversation = store.get_conversation(matter.matter_id)

    queued, created = store.queue_research_job(
        matter.matter_id,
        ACTOR,
        "What time does the generated record report?",
        "Reported time",
        "research-request-" + "a" * 32,
        conversation_id=conversation.conversation_id,
    )
    assert created is True
    assert queued.conversation_id == conversation.conversation_id
    messages = store.messages(matter.matter_id, conversation.conversation_id)
    assert [(item.role, item.content) for item in messages] == [
        ("user", "What time does the generated record report?")
    ]
    assert messages[0].payload["workflow"] == "research"
    with pytest.raises(WorkspaceProblem, match="investigation in progress"):
        store.archive_conversation(
            matter.matter_id, conversation.conversation_id, ACTOR
        )
    active_conversation = store.get_conversation(
        matter.matter_id, conversation.conversation_id
    )
    with pytest.raises(WorkspaceProblem, match="investigation in progress"):
        store.delete_conversation(
            matter.matter_id,
            conversation.conversation_id,
            ACTOR,
            confirmed_title=active_conversation.title,
            acknowledged=True,
        )

    claimed = store.claim_research_job("research-worker-test")
    assert claimed is not None
    completed = store.finish_research_job(claimed.job_id, _research_result())
    assert completed.result_message_id
    messages = store.messages(matter.matter_id, conversation.conversation_id)
    assert len(messages) == 2
    assert messages[-1].role == "assistant"
    assert messages[-1].payload["workflow"] == "research"
    assert messages[-1].payload["research_job_id"] == completed.job_id
    assert messages[-1].payload["claims"][0]["citations"][0]["location"] == "line 1"

    # A repeated completion after a lost worker acknowledgement is idempotent.
    repeated = store.finish_research_job(claimed.job_id, _research_result())
    assert repeated.result_message_id == completed.result_message_id
    assert len(store.messages(matter.matter_id, conversation.conversation_id)) == 2
    store.close()

    restarted = WorkspaceStore(path)
    durable = restarted.research_job(matter.matter_id, ACTOR, claimed.job_id)
    assert durable.conversation_id == conversation.conversation_id
    assert durable.result_message_id == completed.result_message_id
    assert len(restarted.messages(matter.matter_id, conversation.conversation_id)) == 2

    other = restarted.create_matter(
        "Other generated matter", "Isolation fixture", principal.principal_id
    )
    with pytest.raises(WorkspaceProblem):
        restarted.queue_research_job(
            other.matter_id,
            ACTOR,
            "A synthetic cross-matter request",
            "Cross-matter request",
            "research-request-" + "b" * 32,
            conversation_id=conversation.conversation_id,
        )
    restarted.close()


def test_revoked_member_cannot_publish_an_inflight_investigation_result(tmp_path):
    store = WorkspaceStore(tmp_path / "workbench.sqlite")
    owner = store.upsert_principal(
        "test", "owner", "Matter Owner", "owner", preferred_principal_id="principal-owner"
    )
    member = store.upsert_principal(
        "test", "member", "Matter Member", "member", preferred_principal_id="principal-member"
    )
    matter = store.create_matter(
        "Generated revocation matter", "Synthetic fixture", owner.principal_id
    )
    store.add_member(matter.matter_id, member.principal_id, owner.principal_id)
    conversation = store.get_conversation(matter.matter_id)
    queued, created = store.queue_research_job(
        matter.matter_id,
        member.principal_id,
        "What time does the generated record report?",
        "Reported time",
        "research-request-" + "f" * 32,
        conversation_id=conversation.conversation_id,
    )
    assert created is True
    claimed = store.claim_research_job("generated-revocation-worker")
    assert claimed is not None and claimed.job_id == queued.job_id

    store.revoke_member(matter.matter_id, member.principal_id, owner.principal_id)
    with pytest.raises(WorkspaceProblem, match="Access to this matter was removed"):
        store.finish_research_job(claimed.job_id, _research_result())

    assert [message.role for message in store.messages(
        matter.matter_id, conversation.conversation_id
    )] == ["user"]
    assert store.fail_research_job(
        claimed.job_id, "Access to this matter was removed."
    ).state == "failed"
    store.close()


def test_review_continuity_migration_copies_remain_identical():
    root = Path(__file__).resolve().parents[1]
    assert (root / "migrations/sqlite/0023_review_conversation_continuity.sql").read_bytes() == (
        root
        / "src/case_intelligence/migrations/sqlite/0023_review_conversation_continuity.sql"
    ).read_bytes()


def test_review_composer_starts_broader_work_in_the_same_conversation(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=EvidenceEchoGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        created = client.post(
            "/matters",
            data={
                "name": "Generated unified review",
                "descriptor": "Synthetic workflow fixture",
            },
            follow_redirects=False,
        )
        slug = re.search(
            r"/matters/(m-[0-9a-f]{12})/setup", created.headers["location"]
        ).group(1)
        uploaded = client.post(
            f"/matters/{slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "synthetic-record.txt",
                        b"The generated machine record reports the event at 09:14.",
                        "text/plain",
                    ),
                )
            ],
        )
        assert uploaded.status_code == 200

        review = client.get(f"/matters/{slug}")
        assert review.status_code == 200
        assert "Review the record" in review.text
        assert "Investigate more deeply" in review.text
        assert "Check every source" in review.text
        assert "Quick answer" not in review.text
        assert "Deep research" not in review.text
        conversation_id = re.search(
            r'name="conversation" value="([^"]+)"', review.text
        ).group(1)
        request_key = re.search(
            r'name="request_key" value="([^"]+)"', review.text
        ).group(1)

        started = client.post(
            f"/matters/{slug}/ask",
            data={
                "question": "What time does the generated record report?",
                "conversation": conversation_id,
                "request_key": request_key,
                "source_set": "",
                "notebook_mode": "",
                "review_task": "research",
            },
            follow_redirects=False,
        )
        assert started.status_code == 303
        assert f"conversation={conversation_id}" in started.headers["location"]

        deadline = time.monotonic() + 8
        research = None
        while time.monotonic() < deadline:
            matter = client.app.state.workbench.workspace.get_active_matter(slug)
            jobs = client.app.state.workbench.workspace.research_jobs(
                matter.matter_id, matter.owner_id
            )
            research = jobs[0] if jobs else None
            if research is not None and research.state == "succeeded":
                break
            time.sleep(0.02)
        assert research is not None and research.state == "succeeded"
        assert research.conversation_id == conversation_id

        returned = client.get(f"/matters/{slug}?conversation={conversation_id}")
        assert "Investigation ready" in returned.text
        assert "The generated machine record reports the event at 09:14." in returned.text
        citation = re.search(r'class="citation[^\"]*" href="([^"]+)"', returned.text)
        assert citation and client.get(citation.group(1)).status_code == 200
        assert f"/matters/{slug}/research?job={research.job_id}" in returned.text

        # A natural follow-up remains in the same durable thread.
        follow_key = re.search(
            r'name="request_key" value="([^"]+)"', returned.text
        ).group(1)
        follow = client.post(
            f"/matters/{slug}/ask",
            data={
                "question": "Which source supports that?",
                "conversation": conversation_id,
                "request_key": follow_key,
                "source_set": "",
                "notebook_mode": "",
                "review_task": "answer",
            },
            follow_redirects=False,
        )
        assert follow.status_code == 303
        messages = client.app.state.workbench.workspace.messages(
            matter.matter_id, conversation_id
        )
        assert any(
            item.role == "user" and item.content == "Which source supports that?"
            for item in messages
        )
