"""Synthetic regression: automatic suggestions are reviewed from one inbox."""
from __future__ import annotations

import re

from tests.test_automatic_discovery import FIRST, upload, workbench  # noqa: F401
from tests.test_matter_notebook import WEB_ACTOR

SECOND = b"Jordan Sample called Alex Example again about badge: QX-77."


def inbox_names(html: str) -> list[str]:
    section = re.search(r'<section class="suggestion-inbox".*?</section>', html, re.S)
    if section is None:
        return []
    return re.findall(r'<p class="suggestion-title"><a href="[^"]+">([^<]+)</a>', section[0])


def test_inbox_lists_suggestions_most_mentioned_first_with_their_passage(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, matter.slug, "Synthetic call.txt", SECOND)
    bench.run_automatic_discovery_once()
    page = client.get(f"/matters/{matter.slug}/entities").text
    names = inbox_names(page)
    # Same-named suggestions share one row, most-mentioned first; they stay
    # separate identities.
    assert names[:2] == ["Alex Example", "Jordan Sample"]
    assert sorted(names[2:]) == ["03/04/2026", "Amber Cooperative", "QX-77"]
    assert "2 mentions · 2 sources" in page
    assert "Matching names are grouped; a decision applies to each and never merges them." in page
    assert len(bench.entity_service(matter).list(matter.matter_id, WEB_ACTOR)[0]) == 7
    assert 'Suggestions to review <span class="suggestion-total">' in page
    assert "<mark>Jordan Sample</mark>" in page
    # The passage links to the original support.
    assert re.search(rf'class="suggestion-source" href="/matters/{matter.slug}\?support=[0-9a-f]{{40}}#support-pane">Synthetic', page)
    # Guided discovery is still available but collapsed while suggestions wait.
    assert '<details class="notebook-tool-card guided-discovery" aria-labelledby="discovery-heading">' in page


def test_type_filter_narrows_the_inbox(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    bench.run_automatic_discovery_once()
    dates = client.get(f"/matters/{matter.slug}/entities", params={"kind": "dates"}).text
    assert inbox_names(dates) == ["03/04/2026"]
    assert re.search(r'aria-current="page">Dates <span>1</span>', dates)
    people = client.get(f"/matters/{matter.slug}/entities", params={"kind": "people"}).text
    assert sorted(inbox_names(people)) == ["Alex Example", "Jordan Sample"]
    # An unknown filter falls back to all suggestions.
    assert len(inbox_names(client.get(f"/matters/{matter.slug}/entities", params={"kind": "x"}).text)) == 4


def test_one_click_decisions_apply_to_each_same_named_suggestion(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, matter.slug, "Synthetic call.txt", SECOND)
    bench.run_automatic_discovery_once()
    service = bench.entity_service(matter)
    rows, _ = service.list(matter.matter_id, WEB_ACTOR)
    jordans = [row for row in rows if row["display_name"] == "Jordan Sample"]
    amber = next(row for row in rows if row["display_name"] == "Amber Cooperative")
    page = client.get(f"/matters/{matter.slug}/entities", params={"kind": "people"}).text
    targets = re.findall(r'name="targets" value="([^"]+)"><input type="hidden" name="status" value="confirmed"', page)
    jordan_targets = next(value for value in targets if jordans[0]["entity_id"] in value)
    assert sorted(jordan_targets.split(",")) == sorted(f"{row['entity_id']}:{row['revision']}" for row in jordans)
    path = f"/matters/{matter.slug}/entities/actions"
    response = client.post(path, data=dict(action="decide", targets=jordan_targets, status="confirmed", kind="people"),
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/matters/{matter.slug}/entities?kind=people")
    assert response.headers["location"].endswith("#suggestions")
    response = client.post(path, data=dict(action="decide", targets=f"{amber['entity_id']}:{amber['revision']}",
                                           status="dismissed"), follow_redirects=False)
    assert response.status_code == 303
    page = client.get(f"/matters/{matter.slug}/entities").text
    assert sorted(inbox_names(page)) == ["03/04/2026", "Alex Example", "QX-77"]
    for row in jordans:
        entity, mentions, history, _note = service.detail(matter.matter_id, WEB_ACTOR, row["entity_id"])
        assert entity["status"] == "confirmed" and entity["display_name"] == "Jordan Sample"
        assert len(mentions) == 1  # Still separate identities with their own passage.
        assert sorted(entry["action"] for entry in history) == ["edited", "extracted"]
    # A stale click (someone else decided first) changes nothing and shows the current list.
    alexes = [row for row in rows if row["display_name"] == "Alex Example"]
    service.decide(matter.matter_id, WEB_ACTOR, [(alexes[1]["entity_id"], alexes[1]["revision"])], status="dismissed")
    stale = client.post(path, data=dict(action="decide", status="confirmed",
                                        targets=",".join(f"{row['entity_id']}:{row['revision']}" for row in alexes)))
    assert stale.status_code == 409
    assert "That suggestion changed since this page loaded." in stale.text
    assert service.detail(matter.matter_id, WEB_ACTOR, alexes[0]["entity_id"])[0]["status"] == "suggested"
    # Only review decisions, on well-formed targets, are accepted.
    for data in (dict(status="suggested", targets=f"{alexes[0]['entity_id']}:{alexes[0]['revision']}"),
                 dict(status="confirmed", targets="not-a-target"),
                 dict(status="confirmed", targets=f"{alexes[0]['entity_id']}:1,{alexes[0]['entity_id']}:1")):
        refused = client.post(path, data=dict(action="decide", **data))
        assert refused.status_code == 409
        assert service.detail(matter.matter_id, WEB_ACTOR, alexes[0]["entity_id"])[0]["status"] == "suggested"


def test_no_inbox_without_suggestions(workbench):  # noqa: F811
    client, _bench, matter, _runtime = workbench
    page = client.get(f"/matters/{matter.slug}/entities").text
    assert 'class="suggestion-inbox"' not in page
    assert '<details class="notebook-tool-card guided-discovery" aria-labelledby="discovery-heading" open>' in page


def test_only_automatically_found_identities_are_listed(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    bench.run_automatic_discovery_once()
    service = bench.entity_service(matter)
    # A reviewer may record a suggestion by hand; it keeps its own provenance.
    service.create(matter.matter_id, WEB_ACTOR, display_name="Casey Placeholder", status="suggested")
    service.create(matter.matter_id, WEB_ACTOR, display_name="Alex Example", status="suggested")
    page = client.get(f"/matters/{matter.slug}/entities").text
    assert "Casey Placeholder" not in inbox_names(page)
    alex = re.search(r'<li class="suggestion" data-suggestion>(?:(?!</li>).)*?>Alex Example</a>.*?</li>', page, re.S)[0]
    assert "1 mention<" in alex and alex.count('name="targets"') == 2
    assert len(re.search(r'name="targets" value="([^"]+)"', alex)[1].split(",")) == 1


def test_source_count_includes_every_attached_passage(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, matter.slug, "Synthetic call.txt", SECOND)
    bench.run_automatic_discovery_once()
    service = bench.entity_service(matter)
    rows, _ = service.list(matter.matter_id, WEB_ACTOR)
    amber = next(row for row in rows if row["display_name"] == "Amber Cooperative")
    badge = next(row for row in rows if row["display_name"] == "QX-77")
    support = service.detail(matter.matter_id, WEB_ACTOR, badge["entity_id"])[1][0]["support_token"]
    service.attach(matter.matter_id, WEB_ACTOR, amber["entity_id"], expected_revision=amber["revision"], support=support)
    items, _total, _kinds = service.inbox(matter.matter_id, WEB_ACTOR)
    group = next(item for item in items if item["display_name"] == "Amber Cooperative")
    assert (group["identity_count"], group["mention_count"], group["source_count"]) == (1, 2, 2)


def test_highlight_survives_case_folding_that_changes_length():
    from case_intelligence.entity_repository import EntityRepository
    assert EntityRepository.snippet("Straße; Alex Example met", "alex example") == ("Straße; ", "Alex Example", " met")
    assert EntityRepository.snippet("STRASSE Alex", "straße") == ("", "STRASSE", " Alex")


def test_each_grouped_decision_is_audited_against_its_identity(workbench):  # noqa: F811
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    upload(client, matter.slug, "Synthetic call.txt", SECOND)
    bench.run_automatic_discovery_once()
    rows, _ = bench.entity_service(matter).list(matter.matter_id, WEB_ACTOR)
    jordans = [row for row in rows if row["display_name"] == "Jordan Sample"]
    targets = ",".join(f"{row['entity_id']}:{row['revision']}" for row in jordans)
    response = client.post(f"/matters/{matter.slug}/entities/actions",
                           data=dict(action="decide", targets=targets, status="confirmed"), follow_redirects=False)
    assert response.status_code == 303
    events = [event for event in bench.workspace.audit_events(matter.matter_id) if event.action == "entity.decide"]
    assert sorted(event.object_id for event in events) == sorted(row["entity_id"] for row in jordans)
    assert {event.object_type for event in events} == {"entity"}


def test_inbox_work_grows_linearly_with_suggestions(workbench):  # noqa: F811
    import hashlib
    client, bench, matter, _runtime = workbench
    upload(client, matter.slug, "Synthetic memo.txt", FIRST)
    bench.run_automatic_discovery_once()
    service = bench.entity_service(matter)
    rows, _ = service.list(matter.matter_id, WEB_ACTOR)
    sample = service.detail(matter.matter_id, WEB_ACTOR, rows[0]["entity_id"])[1][0]
    connection = bench.workspace.connection

    def add(count, start):
        with connection:
            for index in range(start, start + count):
                entity_id = f"synthetic-entity-{index:06d}"
                connection.execute(
                    "INSERT INTO workbench_entity(entity_id,matter_id,entity_type,display_name,status,origin,"
                    "created_by,created_at,updated_by,updated_at) VALUES (?,?,'person',?,'suggested','extraction',"
                    "?,'2026-01-01T00:00:00Z',?,'2026-01-01T00:00:00Z')",
                    (entity_id, matter.matter_id, f"Synthetic Person {index:06d}", WEB_ACTOR, WEB_ACTOR))
                connection.execute(
                    "INSERT INTO workbench_entity_mention(mention_id,matter_id,entity_id,document_id,source_version_id,"
                    "source_name,location,unit_number,chunk_id,excerpt_digest,excerpt,support_token,origin,created_by,"
                    "created_at) VALUES (?,?,?,?,?,?,?,1,?,?,?,?,'extraction',?,'2026-01-01T00:00:00Z')",
                    (f"synthetic-mention-{index:06d}", matter.matter_id, entity_id, sample["document_id"],
                     sample["source_version_id"], sample["source_name"], sample["location"], sample["chunk_id"],
                     hashlib.sha256(str(index).encode()).hexdigest(), f"Synthetic Person {index:06d} called.",
                     sample["support_token"], WEB_ACTOR))

    def steps():
        counted = [0]

        def tick():
            counted[0] += 1
            return 0
        connection.set_progress_handler(tick, 1000)
        try:
            items, total, _kinds = service.inbox(matter.matter_id, WEB_ACTOR)
        finally:
            connection.set_progress_handler(None, 0)
        assert len(items) == 25
        return counted[0], total

    add(1000, 0)
    small, total = steps()
    add(3000, 1000)
    large, larger_total = steps()
    assert larger_total - total == 3000
    # Four times the suggestions costs about four times the work, not sixteen.
    assert large <= 6 * max(small, 1), (small, large)
