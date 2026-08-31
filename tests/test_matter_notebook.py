from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore


ACTOR = "development-notebook-user"
WEB_ACTOR = "development-taylor-morgan"


def _seed(store: WorkspaceStore, actor: str = ACTOR) -> None:
    store.upsert_principal(
        "test",
        actor,
        "Notebook Reviewer",
        actor,
        preferred_principal_id=actor,
    )


def _reference(suffix: str = "a") -> dict[str, object]:
    return {
        "document_id": "document-" + suffix * 32,
        "source_version_id": "source-version-" + suffix * 32,
        "source_name": "Interview notes.txt",
        "location": "Lines 1–3",
        "unit_number": 1,
        "chunk_id": "chunk-1",
        "excerpt_digest": suffix * 64,
        "excerpt": "Officer Jane Rivera met at Central Park on August 14, 2026.",
        "support_token": suffix * 40,
    }


def test_notebook_migration_matches_operator_copy():
    root = Path(__file__).parents[1]
    assert (
        root / "src/case_intelligence/migrations/sqlite/0010_matter_notebook.sql"
    ).read_bytes() == (
        root / "migrations/sqlite/0010_matter_notebook.sql"
    ).read_bytes()


def test_notebook_crud_provenance_isolation_and_answer_snapshot(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    _seed(store)
    matter = store.create_matter("Notebook matter", "Synthetic", ACTOR)
    other = store.create_matter("Other matter", "Synthetic", ACTOR)
    conversation = store.get_conversation(matter.matter_id)

    item, created = store.create_notebook_item(
        matter.matter_id,
        ACTOR,
        item_type="person",
        status="suggested",
        title="Officer Jane Rivera",
        body="Named in an interview note.",
        origin="extraction",
        dedupe_key="extraction:person:officer-jane-rivera",
        references=(_reference(),),
    )
    duplicate, duplicate_created = store.create_notebook_item(
        matter.matter_id,
        ACTOR,
        item_type="person",
        status="suggested",
        title="Officer Jane Rivera",
        body="A duplicate candidate.",
        origin="extraction",
        dedupe_key="extraction:person:officer-jane-rivera",
        references=(_reference(),),
    )
    assert created is True and duplicate_created is False
    assert duplicate.item_id == item.item_id
    assert store.notebook_references(matter.matter_id, ACTOR, item.item_id)[0].support_token == "a" * 40
    with pytest.raises(KeyError):
        store.notebook_item(other.matter_id, ACTOR, item.item_id)
    with pytest.raises(KeyError):
        store.update_notebook_item(
            other.matter_id,
            ACTOR,
            item.item_id,
            item_type="person",
            status="confirmed",
            title="Cross-matter write",
        )

    confirmed = store.set_notebook_item_status(
        matter.matter_id, ACTOR, item.item_id, "confirmed"
    )
    assert confirmed.status == "confirmed"
    page = store.notebook_page(
        matter.matter_id, ACTOR, query="Rivera", item_type="person"
    )
    assert page.total == 1
    assert page.counts["confirmed"] == 1

    job, _ = store.queue_answer_job(
        matter.matter_id,
        conversation.conversation_id,
        ACTOR,
        "What corroborates this identification?",
        "answer-request-" + "b" * 32,
        notebook_mode="confirmed",
    )
    mode, snapshot = store.answer_notebook_context(matter.matter_id, job.job_id)
    assert mode == "confirmed"
    assert [entry.title for entry in snapshot] == ["Officer Jane Rivera"]
    store.update_notebook_item(
        matter.matter_id,
        ACTOR,
        item.item_id,
        item_type="person",
        status="disputed",
        title="Officer Jane Rivera — disputed",
        body="The saved scope must not mutate.",
    )
    assert store.answer_notebook_context(matter.matter_id, job.job_id)[1][0].title == "Officer Jane Rivera"
    store.delete_notebook_item(matter.matter_id, ACTOR, item.item_id)
    assert store.notebook_page(matter.matter_id, ACTOR).total == 0
    assert store.answer_notebook_context(matter.matter_id, job.job_id)[1][0].title == "Officer Jane Rivera"

    with pytest.raises(WorkspaceProblem, match="at least one"):
        store.queue_answer_job(
            matter.matter_id,
            conversation.conversation_id,
            ACTOR,
            "Use a missing selection",
            "answer-request-" + "c" * 32,
            notebook_mode="selected",
        )
    store.close()


class EchoGenerator:
    available = True

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        evidence = kwargs["evidence"]
        return {
            "answerable": True,
            "claims": [
                {"text": evidence[0].excerpt[:800], "evidence_ids": [evidence[0].evidence_id]}
            ],
            "limitation": None,
            "missing_information": "",
        }


def _create_matter(client: TestClient, name: str = "Notebook web matter") -> str:
    response = client.post(
        "/matters", data={"name": name, "descriptor": "Synthetic notebook test"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("/")[2]


def _wait(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    deadline = time.monotonic() + 5
    result = payload
    while time.monotonic() < deadline and result["state"] not in {"succeeded", "failed"}:
        time.sleep(0.01)
        result = client.get(str(result["status_url"])).json()
    assert result["state"] == "succeeded", result.get("message")
    return result


def test_notebook_web_capture_review_context_suggestions_and_exports(tmp_path):
    generator = EchoGenerator()
    with TestClient(
        create_workbench_app(tmp_path / "runtime", generator=generator, auth_mode="test")
    ) as client:
        slug = _create_matter(client)
        uploaded = client.post(
            f"/matters/{slug}/uploads",
            files=[
                (
                    "files",
                    (
                        "Interview notes.txt",
                        b"Officer Jane Rivera met at Central Park on August 14, 2026.\nThe meeting was recorded in the report.\n",
                        "text/plain",
                    ),
                )
            ],
        )
        assert uploaded.status_code == 200
        matter = client.app.state.workbench.matter(slug, WEB_ACTOR)
        conversation = client.app.state.workbench.workspace.get_conversation(matter.matter_id)

        manual = client.post(
            f"/matters/{slug}/notebook/items",
            data={
                "item_type": "issue",
                "status": "needs_review",
                "title": "Confirm meeting location",
                "body": "=HYPERLINK(\"https://example.invalid\")",
                "pinned": "yes",
            },
            follow_redirects=False,
        )
        assert manual.status_code == 303
        notebook = client.get(f"/matters/{slug}/notebook")
        assert "Confirm meeting location" in notebook.text
        assert "Build review work product as you go" in notebook.text
        assert "Save case note" in notebook.text
        assert 'class="matter-section-tabs"' in notebook.text
        assert "Find review suggestions" in notebook.text

        search = client.get(
            f"/matters/{slug}", params={"mode": "search", "q": "Central Park"}
        )
        token = re.search(rf"/matters/{slug}\?support=([0-9a-f]{{40}})", search.text)
        assert token
        captured = client.post(
            f"/matters/{slug}/notebook/from-support/{token.group(1)}",
            follow_redirects=False,
        )
        assert captured.status_code == 303

        first = client.post(
            f"/matters/{slug}/ask",
            data={
                "conversation": conversation.conversation_id,
                "question": "Who met at Central Park?",
                "request_key": "answer-request-" + "d" * 32,
            },
            headers={"Accept": "application/json"},
        )
        assert first.status_code == 202
        first_job = _wait(client, first.json())
        answer_page = client.get(str(first_job["workspace_url"]).split("#", 1)[0])
        message = next(
            item
            for item in client.app.state.workbench.workspace.messages(
                matter.matter_id, conversation.conversation_id
            )
            if item.role == "assistant"
        )
        assert "Save passage to case notes" in answer_page.text
        saved_claim = client.post(
            f"/matters/{slug}/conversations/{conversation.conversation_id}/messages/{message.message_id}/notebook/claims/0",
            follow_redirects=False,
        )
        assert saved_claim.status_code == 303
        saved_item = next(
            item
            for item in client.app.state.workbench.workspace.all_notebook_items(
                matter.matter_id, WEB_ACTOR
            )
            if item.origin == "answer"
        )
        confirmed = client.post(
            f"/matters/{slug}/notebook/items/{saved_item.item_id}/status",
            data={"status": "confirmed"},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303

        second = client.post(
            f"/matters/{slug}/ask",
            data={
                "conversation": conversation.conversation_id,
                "question": "What corroborates that?",
                "request_key": "answer-request-" + "e" * 32,
                "notebook_mode": "confirmed",
            },
            headers={"Accept": "application/json"},
        )
        assert second.status_code == 202
        second_job = _wait(client, second.json())
        assert "Officer Jane Rivera" in str(generator.calls[-1]["working_context"])
        contextual_page = client.get(str(second_job["workspace_url"]).split("#", 1)[0])
        assert "user-selected notebook item" in contextual_page.text

        suggestions = client.post(
            f"/matters/{slug}/notebook/suggestions", follow_redirects=False
        )
        assert suggestions.status_code == 303
        suggestion_page = client.get(suggestions.headers["location"])
        assert "Officer Jane Rivera" in suggestion_page.text
        assert "Central Park" in suggestion_page.text
        assert "August 14, 2026" in suggestion_page.text

        csv_export = client.get(
            f"/matters/{slug}/notebook/export", params={"format": "csv"}
        )
        assert csv_export.status_code == 200
        assert csv_export.content.startswith(b"\xef\xbb\xbf")
        assert "'=HYPERLINK" in csv_export.content.decode("utf-8-sig")

        bundle = client.get(f"/matters/{slug}/export")
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            assert "notebook/matter-notebook.docx" in archive.namelist()
            assert "notebook/notebook.json" in archive.namelist()
            assert archive.testzip() is None
