"""Synthetic regression: one slim, consistent matter bar on every matter page."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re

from tests.test_saved_answer_report_support import ACTOR, cedar  # noqa: F401

DESTINATIONS = ["Home", "Review", "Ask", "Search", "Case file", "Settings"]
CASE_FILE = ["Overview", "Notes", "People & things", "Timeline", "Review map", "Reports"]


class Navigation(HTMLParser):
    """Collect link labels and current-page markers inside named nav elements."""

    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.depth = 0
        self.links: list[dict] = []
        self.current: dict | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "nav" and values.get("aria-label") == self.label:
            self.depth = 1
        elif self.depth and tag == "nav":
            self.depth += 1
        elif self.depth and tag == "a":
            self.current = {"href": values.get("href"), "current": values.get("aria-current"), "text": ""}

    def handle_endtag(self, tag):
        if self.depth and tag == "a" and self.current is not None:
            self.current["text"] = " ".join(self.current["text"].split())
            self.links.append(self.current)
            self.current = None
        elif self.depth and tag == "nav":
            self.depth -= 1

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data


def navigation(html: str, label: str) -> list[dict]:
    parser = Navigation(label)
    parser.feed(html)
    return parser.links


def test_every_matter_page_offers_the_same_six_destinations(cedar):  # noqa: F811
    client, bench, matter, documents = cedar
    prefix = f"/matters/{matter.slug}"
    store = bench.source_store(matter)
    reader = f"{prefix}/sources/{store.action_token(documents['pdf'])}?unit=1"
    expected_current = {
        f"{prefix}/home": "Home",
        f"{prefix}/setup?view=list&page_size=100": "Review",
        f"{prefix}/full-review": "Review",
        reader: "Review",
        prefix: "Ask",
        f"{prefix}/exact-search": "Search",
        f"{prefix}/work-product": "Case file",
        f"{prefix}/notebook": "Case file",
        f"{prefix}/entities": "Case file",
        f"{prefix}/chronology": "Case file",
        f"{prefix}/reports": "Case file",
        f"{prefix}/export-readiness": "Case file",
        f"{prefix}/settings": "Settings",
    }
    for path, current in expected_current.items():
        page = client.get(path)
        assert page.status_code == 200, path
        links = navigation(page.text, "Matter workspace sections")
        assert [link["text"] for link in links] == DESTINATIONS, path
        assert [link["text"] for link in links if link["current"] == "page"] == [current], path
        assert page.text.count('aria-label="Matter workspace sections"') == 1, path


def test_case_file_sections_share_one_sub_navigation(cedar):  # noqa: F811
    client, _bench, matter, _documents = cedar
    prefix = f"/matters/{matter.slug}"
    for path, current in {
        "/work-product": "Overview", "/notebook": "Notes", "/entities": "People & things",
        "/chronology": "Timeline", "/analysis": "Review map", "/reports": "Reports",
    }.items():
        page = client.get(prefix + path)
        assert page.status_code == 200, path
        links = navigation(page.text, "Case file sections")
        assert [link["text"] for link in links] == CASE_FILE, path
        assert [link["text"] for link in links if link["current"] == "page"] == [current], path
    assert "Case file sections" not in client.get(f"{prefix}/home").text


def test_matter_search_box_submits_an_ordinary_exact_search(cedar):  # noqa: F811
    client, _bench, matter, _documents = cedar
    home = client.get(f"/matters/{matter.slug}/home").text
    form = re.search(r'<form class="matter-bar-search"[^>]*action="([^"]+)"[^>]*>(.*?)</form>', home, re.S)
    assert form is not None
    assert form[1] == f"/matters/{matter.slug}/exact-search"
    assert 'name="words"' in form[2] and 'name="search" value="1"' in form[2]
    result = client.get(form[1], params={"search": "1", "advanced": "0", "words": "gauge"})
    assert result.status_code == 200
    # The Search page has its own full form; it does not repeat the bar search.
    assert 'class="matter-bar-search"' not in result.text


def test_source_reader_keeps_matter_navigation_visible(cedar):  # noqa: F811
    client, bench, matter, documents = cedar
    store = bench.source_store(matter)
    page = client.get(f"/matters/{matter.slug}/sources/{store.action_token(documents['pdf'])}?unit=1").text
    assert "<summary>Workspace</summary>" not in page
    bar = page.index('aria-label="Matter workspace sections"')
    assert bar < page.index('class="source-review-heading"')
    assert ">Save note</button>" in page and "Save human note" not in page


def test_ready_readiness_offers_extraction_limits_without_losing_guidance(cedar):  # noqa: F811
    client, _bench, matter, _documents = cedar
    page = client.get(f"/matters/{matter.slug}/home").text
    assert 'data-readiness-limits-toggle aria-expanded="false" aria-controls="matter-readiness-guidance" hidden' in page
    # The guidance stays in the document for assistive technology and no-script use.
    assert 'id="matter-readiness-guidance" data-readiness-guidance>' in page


def test_retention_warning_is_full_on_home_and_a_chip_elsewhere(cedar):  # noqa: F811
    client, bench, matter, _documents = cedar
    bench.workspace.set_matter_retention(
        matter.matter_id, ACTOR, datetime.now(timezone.utc) + timedelta(days=10))
    prefix = f"/matters/{matter.slug}"
    home = client.get(f"{prefix}/home").text
    assert 'class="retention-notice tone-attention"' in home
    assert 'class="matter-bar-retention' not in home
    for path in ("/setup?view=list&page_size=100", "/notebook", ""):
        page = client.get(prefix + path).text
        assert 'class="retention-notice' not in page, path
        assert f'href="{prefix}/home#matter-retention"' in page, path
        assert "Scheduled to close in" in page, path


def test_imminent_deletion_stays_prominent_everywhere(cedar, monkeypatch):  # noqa: F811
    client, bench, matter, _documents = cedar
    now = datetime.now(timezone.utc)
    bench.workspace.set_matter_retention(matter.matter_id, ACTOR, now + timedelta(days=2))
    # The review period has ended; the matter is in its deletion grace period.
    monkeypatch.setattr(bench.workspace, "current_time", lambda: now + timedelta(days=3))
    prefix = f"/matters/{matter.slug}"
    # Every page with the matter bar, including pages that never embedded the
    # notice themselves, shows the imminent-deletion notice exactly once.
    for path in ("/home", "/notebook", "/exact-search", "/settings", "/setup?view=list", "/export-readiness", ""):
        page = client.get(prefix + path)
        assert page.status_code == 200, path
        assert page.text.count('class="retention-notice tone-danger"') == 1, path
        assert 'class="matter-bar-retention' not in page.text, path
