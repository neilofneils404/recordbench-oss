from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app


def _matter(client: TestClient) -> tuple[str, str, str]:
    response = client.post(
        "/matters",
        data={
            "name": "Generated guided review",
            "descriptor": "Synthetic usability fixture",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    slug = response.headers["location"].split("/")[2]
    matter = client.app.state.workbench.workspace.get_active_matter(slug)
    return slug, matter.matter_id, matter.owner_id


def test_matter_home_explains_the_four_review_jobs(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug, _, _ = _matter(client)
        page = client.get(f"/matters/{slug}/home")
        assert page.status_code == 200
        assert 'data-task-launcher' in page.text
        assert "What do you want to accomplish?" in page.text
        for label in (
            "Ask a focused question",
            "Investigate a topic",
            "Screen every source",
            "Review records manually",
        ):
            assert label in page.text
        assert "not a collection-wide screen" in page.text
        assert "time scales with the collection" in page.text


def test_workflow_pages_default_to_quick_question_without_overriding_user_choice(
    tmp_path,
):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug, _, _ = _matter(client)
        setup = client.get(f"/matters/{slug}/setup")
        research = client.get(f"/matters/{slug}/research")
        full_review = client.get(f"/matters/{slug}/full-review")

        assert 'data-assistant-default="open"' in setup.text
        for page in (research, full_review):
            assert page.status_code == 200
            assert 'data-assistant-default="collapsed"' in page.text
            assert 'data-assistant-presentation="quick"' in page.text
            assert "Quick question" in page.text
        assert "recordbench:assistant:display:v2" in (
            client.get("/static/case-intelligence.js").text
        )


def test_activity_center_is_global_matter_bound_and_content_minimized(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug, matter_id, owner_id = _matter(client)
        queued, created = client.app.state.workbench.workspace.queue_research_job(
            matter_id,
            owner_id,
            "Synthetic private question that must not appear in activity.",
            "Generated chronology review",
            "research-request-" + "a" * 32,
        )
        assert created is True

        workspace = client.app.state.workbench.workspace
        foreign_owner = workspace.upsert_principal(
            "test",
            "foreign-activity-user",
            "Foreign Activity User",
            "foreign.activity",
        )
        foreign_matter = workspace.create_matter(
            "Foreign generated matter",
            "Synthetic access-control fixture",
            foreign_owner.principal_id,
        )
        workspace.queue_research_job(
            foreign_matter.matter_id,
            foreign_owner.principal_id,
            "Foreign synthetic question",
            "Foreign generated chronology",
            "research-request-" + "b" * 32,
        )

        page = client.get(f"/matters/{slug}/home")
        assert 'data-activity-toggle' in page.text
        assert 'data-activity-drawer' in page.text
        assert f'data-activity-url="/activity?matter={slug}"' in page.text

        activity = client.get(f"/activity?matter={slug}")
        assert activity.status_code == 200
        assert 'data-activity-content' in activity.text
        assert "Generated chronology review" in activity.text
        assert "Synthetic private question" not in activity.text
        assert "Foreign generated matter" not in activity.text
        assert "Foreign generated chronology" not in activity.text
        assert f"job={queued.job_id}" in activity.text
        assert "Work continues if you leave this page" in activity.text
        assert 'data-poll-after-ms="3000"' in activity.text


def test_full_review_setup_uses_plain_language_examples_and_frozen_scope(tmp_path):
    app = create_workbench_app(
        tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="test"
    )
    with TestClient(app) as client:
        slug, _, _ = _matter(client)
        page = client.get(f"/matters/{slug}/full-review")
        assert page.status_code == 200
        for text in (
            "Start from an example",
            "Name this review",
            "What should RecordBench mark for review?",
            "What should RecordBench leave out?",
            "Recommended: test on up to 50",
            "The source list is frozen when the run starts",
        ):
            assert text in page.text
        assert len(re.findall(r"data-criterion-template=", page.text)) >= 3
        template = (
            Path(__file__).parents[1]
            / "src/case_intelligence/templates/workbench_full_review.html"
        ).read_text()
        assert "What these numbers mean" in template
