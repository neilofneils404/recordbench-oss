from __future__ import annotations

from datetime import datetime, timezone

import pytest

from case_intelligence.workspace_store import WorkspaceProblem, WorkspaceStore


FIXED = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)


def _seed(store: WorkspaceStore) -> None:
    store.upsert_principal(
        "test",
        "dev-taylor",
        "Taylor Morgan",
        "dev-taylor",
        preferred_principal_id="dev-taylor",
    )


def test_matter_and_conversation_persist_and_remain_bound(tmp_path):
    path = tmp_path / "workbench.sqlite"
    store = WorkspaceStore(path, clock=lambda: FIXED)
    _seed(store)
    first = store.create_matter(
        "Synthetic Matter AURORA-17", "Training dataset · Review exercise", "dev-taylor"
    )
    second = store.create_matter("Synthetic Matter COBALT-9", "Training dataset", "dev-taylor")
    first_conversation = store.get_conversation(first.matter_id)
    second_conversation = store.get_conversation(second.matter_id)
    store.append_message(
        first.matter_id,
        first_conversation.conversation_id,
        "user",
        "When was the canvas bag observed?",
    )
    store.append_message(
        first.matter_id,
        first_conversation.conversation_id,
        "assistant",
        "The reports give two times.",
        {"kind": "generated", "citations": [{"source": "Incident reports.pdf"}]},
    )
    with pytest.raises(KeyError):
        store.messages(second.matter_id, first_conversation.conversation_id)
    with pytest.raises(KeyError):
        store.append_message(
            second.matter_id, first_conversation.conversation_id, "user", "cross matter"
        )
    assert store.messages(second.matter_id, second_conversation.conversation_id) == ()
    store.close()

    reopened = WorkspaceStore(path, clock=lambda: FIXED)
    matters = reopened.list_matters("dev-taylor")
    assert {item.slug for item in matters} == {first.slug, second.slug}
    loaded = reopened.get_matter(first.slug, "dev-taylor")
    messages = reopened.messages(
        loaded.matter_id, reopened.get_conversation(loaded.matter_id).conversation_id
    )
    assert [item.role for item in messages] == ["user", "assistant"]
    assert messages[1].payload["kind"] == "generated"
    reopened.close()


def test_workspace_rejects_unsafe_or_unbounded_staff_text(tmp_path):
    store = WorkspaceStore(tmp_path / "workbench.sqlite", clock=lambda: FIXED)
    _seed(store)
    with pytest.raises(WorkspaceProblem, match="required"):
        store.create_matter("  ", "", "dev-taylor")
    with pytest.raises(WorkspaceProblem, match="unsupported"):
        store.create_matter("Rowan\u202e", "", "dev-taylor")
    with pytest.raises(WorkspaceProblem, match="too long"):
        store.create_matter("R" * 141, "", "dev-taylor")
    with pytest.raises(KeyError):
        store.get_matter("../rowan", "dev-taylor")
    store.close()


def test_conversation_summaries_auto_title_and_explicit_rename(tmp_path):
    store = WorkspaceStore(tmp_path / "workbench.sqlite", clock=lambda: FIXED)
    _seed(store)
    matter = store.create_matter("Synthetic continuity matter", "", "dev-taylor")
    first = store.get_conversation(matter.matter_id)
    second = store.create_conversation(matter.matter_id)

    job, created = store.queue_answer_job(
        matter.matter_id,
        second.conversation_id,
        "dev-taylor",
        "What do the reports say about the unusually long sequence of events near the loading dock after midnight?",
        "answer-request-" + "a" * 32,
    )
    assert created is True
    assert job.conversation_id == second.conversation_id

    summaries = store.conversation_summaries(matter.matter_id)
    titled = next(item for item in summaries if item.conversation_id == second.conversation_id)
    assert titled.title.startswith("What do the reports say")
    assert titled.title.endswith("…")
    assert len(titled.title) <= 72
    assert titled.message_count == 1

    renamed = store.rename_conversation(
        matter.matter_id, second.conversation_id, "Loading dock timeline"
    )
    assert renamed.title == "Loading dock timeline"
    assert store.get_conversation(matter.matter_id, first.conversation_id).title == "Case review"
    with pytest.raises(KeyError):
        store.rename_conversation(
            matter.matter_id, "conversation-" + "f" * 32, "Wrong matter"
        )
    store.close()
