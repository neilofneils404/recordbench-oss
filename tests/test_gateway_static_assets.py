"""Synthetic regression for the installed HTTPS gateway's internal HTTP hop."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from fastapi.testclient import TestClient

from tests.test_browser_local_accounts import configured_app, login


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        value = values.get("src") if tag in {"script", "img"} else values.get("href") if tag == "link" else None
        if value and "/static/" in value:
            self.urls.append(value)


def test_workspace_assets_retain_browser_https_origin_across_internal_http_hop(tmp_path):
    app, _ = configured_app(tmp_path)
    # Nginx terminates TLS and forwards Host without the external port. Do not
    # broaden trusted proxy headers to manufacture the browser's origin here.

    @app.middleware("http")
    async def gateway_hop(request, call_next):
        request.scope["scheme"] = "http"
        request.scope["headers"] = [
            (key, b"localhost" if key == b"host" else value)
            for key, value in request.scope["headers"]
        ]
        return await call_next(request)

    with TestClient(app, base_url="https://localhost:8443") as backend:
        assert login(backend).status_code == 303
        response = backend.get("/admin/setup", headers={"X-Forwarded-Proto": "https"})
        assert response.status_code == 200
        assets = Assets()
        assets.feed(response.text)
        assert any("case-intelligence.js" in url for url in assets.urls)
        assert any("case-intelligence.css" in url for url in assets.urls)
        for asset in assets.urls:
            resolved = urlsplit(urljoin("https://localhost:8443/auth/login", asset))
            assert (resolved.scheme, resolved.netloc) == ("https", "localhost:8443")
            assert backend.get(resolved.path).status_code == 200
