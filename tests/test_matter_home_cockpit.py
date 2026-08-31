from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app
from case_intelligence.workspace_store import WorkspaceStore


ACTOR = "development-taylor-morgan"
FIXED = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)


def _matter(client: TestClient, name: str = "Synthetic cockpit matter") -> str:
    response = client.post(
        "/matters",
        data={"name": name, "descriptor": "Generated cockpit acceptance"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("/")[2]


def test_activity_is_per_user_matter_bound_and_upserts_locator(tmp_path):
    store = WorkspaceStore(tmp_path / "workbench.sqlite", clock=lambda: FIXED)
    store.upsert_principal(
        "test", "owner", "Owner Example", "owner", preferred_principal_id="test-owner"
    )
    store.upsert_principal(
        "test", "member", "Member Example", "member", preferred_principal_id="test-member"
    )
    first = store.create_matter("First synthetic matter", "", "test-owner")
    second = store.create_matter("Second synthetic matter", "", "test-owner")
    store.add_member(first.matter_id, "test-member", "test-owner")

    source_id = "a" * 32
    created = store.record_matter_activity(
        first.matter_id, "test-owner", "source", source_id, locator=1_000
    )
    updated = store.record_matter_activity(
        first.matter_id, "test-owner", "source", source_id, locator=9_500
    )
    assert updated.activity_id == created.activity_id
    assert updated.locator == 9_500
    assert store.recent_matter_activities(first.matter_id, "test-member") == ()
    assert store.recent_matter_activities(second.matter_id, "test-owner") == ()
    with pytest.raises(KeyError):
        store.record_matter_activity(
            second.matter_id, "test-member", "source", source_id
        )

    store.remove_matter_activity_object(first.matter_id, "source", source_id)
    assert store.recent_matter_activities(first.matter_id, "test-owner") == ()
    store.close()


def test_home_work_product_and_review_continue_flow(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug = _matter(client)
        uploaded = client.post(
            f"/matters/{slug}/uploads",
            files=[
                ("files", ("first.txt", b"Generated first source.\n", "text/plain")),
                ("files", ("second.txt", b"Generated second source.\n", "text/plain")),
            ],
        )
        assert uploaded.status_code == 200
        bench = client.app.state.workbench
        matter = bench.matter(slug, ACTOR)
        rows = bench.workspace.source_catalog_page(
            matter.matter_id, sort="oldest", limit=10
        ).items
        assert len(rows) == 2

        home = client.get(f"/matters/{slug}/home")
        assert home.status_code == 200
        for label in ("Home", "Review", "Sources", "Work product"):
            assert f">{label}<" in home.text
        assert "Pick up where you left off" in home.text
        assert "Review next" in home.text
        assert home.text.count('class="queue-row"') == 2

        first = rows[0]
        opened = client.get(f"/matters/{slug}/sources/{first.action_token}?unit=1")
        assert opened.status_code == 200
        assert "Mark reviewed and continue" in opened.text
        activities = bench.workspace.recent_matter_activities(
            matter.matter_id, ACTOR
        )
        assert activities[0].object_id == first.document_id
        assert activities[0].locator == 1

        advanced = client.post(
            f"/matters/{slug}/sources/{first.action_token}/review-next",
            follow_redirects=False,
        )
        assert advanced.status_code == 303
        assert rows[1].action_token in advanced.headers["location"]
        assert bench.workspace.source_catalog_record(
            matter.matter_id, first.document_id
        ).review_state == "reviewed"

        finished = client.post(
            f"/matters/{slug}/sources/{rows[1].action_token}/review-next",
            follow_redirects=False,
        )
        assert finished.status_code == 303
        assert finished.headers["location"].startswith(f"/matters/{slug}/home")
        assert "Review+queue+complete" in finished.headers["location"]

        work_product = client.get(f"/matters/{slug}/work-product")
        assert work_product.status_code == 200
        assert "Turn review into something useful" in work_product.text
        assert "Case notes" in work_product.text
        assert "Review map" in work_product.text
        assert "Reports" in work_product.text
