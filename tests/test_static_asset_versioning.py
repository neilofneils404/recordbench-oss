"""Synthetic regression: pages never pair new markup with stale cached styles."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from case_intelligence import static_assets
from case_intelligence.static_assets import (
    UNVERSIONED_CACHE_CONTROL,
    VERSIONED_CACHE_CONTROL,
    asset_url,
    asset_version,
)
from tests.test_browser_local_accounts import configured_app, login

TEMPLATES = Path(__file__).parents[1] / "src/case_intelligence/templates"


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        value = values.get("src") if tag in {"script", "img"} else values.get("href") if tag == "link" else None
        if value and value.startswith("/static/"):
            self.urls.append(value)


def test_asset_url_carries_content_digest():
    url = asset_url("workspace-layout.css")
    parts = urlsplit(url)
    assert parts.path == "/static/workspace-layout.css"
    assert parse_qs(parts.query)["v"] == [asset_version("workspace-layout.css")]
    assert len(asset_version("workspace-layout.css")) == 12


def test_asset_version_changes_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(static_assets, "STATIC_ROOT", tmp_path)
    monkeypatch.setattr(static_assets, "_digests", {})
    stylesheet = tmp_path / "synthetic.css"
    stylesheet.write_text("body { color: black; }", encoding="utf-8")
    first = asset_url("synthetic.css")
    stylesheet.write_text("body { color: navy; margin: 0; }", encoding="utf-8")
    assert asset_url("synthetic.css") != first


def test_asset_url_refuses_paths_outside_static_root():
    assert asset_url("../workbench.py") == "/static/../workbench.py"
    assert asset_version("../workbench.py") is None
    assert asset_version("missing.css") is None


def test_templates_do_not_reference_unversioned_static_files():
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert "url_for('static'" not in text, template.name
        assert '"/static/' not in text, template.name


def test_rendered_pages_use_versioned_assets_and_matching_cache_policy(tmp_path):
    app, _ = configured_app(tmp_path)
    with TestClient(app, base_url="https://localhost") as client:
        assert login(client).status_code == 303
        page = client.get("/admin/setup")
        assert page.status_code == 200
        assets = Assets()
        assets.feed(page.text)
        assert any("workspace-layout.css" in url for url in assets.urls)
        for url in assets.urls:
            assert "?v=" in url, url
            response = client.get(url)
            assert response.status_code == 200
            assert response.headers["cache-control"] == VERSIONED_CACHE_CONTROL

        bare = client.get("/static/workspace-layout.css")
        assert bare.headers["cache-control"] == UNVERSIONED_CACHE_CONTROL
        stale = client.get("/static/workspace-layout.css?v=000000000000")
        assert stale.headers["cache-control"] == UNVERSIONED_CACHE_CONTROL
