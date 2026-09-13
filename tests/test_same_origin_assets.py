"""Synthetic browser-origin contract when a TLS gateway forwards backend HTTP."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
import pytest


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") in {"stylesheet", "icon"}:
            self.assets.append(values["href"])
        elif tag in {"script", "img", "source"} and "/static/" in values.get("src", ""):
            self.assets.append(values["src"])


@pytest.mark.parametrize("template", ["workbench_base.html", "workbench_login.html", "workspace.html", "source.html"])
@pytest.mark.parametrize("root_path", ["", "/synthetic-prefix"])
def test_static_assets_keep_external_https_origin_and_port(template, root_path):
    package = Path(__file__).parents[1] / "src/case_intelligence"
    templates = Jinja2Templates(directory=str(package / "templates"))
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(package / "static")), name="static")

    @app.get("/page")
    def page(request: Request):
        # The gateway's backend request has neither its external scheme nor port.
        assert request.url.scheme == "http" and request.url.port is None
        return templates.TemplateResponse(request=request, name=template, context={
            "product_name": "RecordBench", "auth_mode": "local", "slug": "alpha",
            "matter": {"name": "Synthetic matter", "subtitle": "Synthetic sources"},
            "document": {"name": "Synthetic source", "lines": [(1, "Synthetic text.")]},
            "sources": (), "matters": {}, "cues": (), "search_results": (),
        })

    async def backend_scope(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "scheme": "http", "root_path": root_path,
                     "headers": [(key, b"127.0.0.1" if key == b"host" else value)
                                 for key, value in scope["headers"]]}
        await app(scope, receive, send)

    origin = "https://127.0.0.1:9443"
    with TestClient(backend_scope, base_url=origin) as client:
        response = client.get(root_path + "/page")
        assert response.status_code == 200
        parser = AssetParser()
        parser.feed(response.text)
        assert parser.assets
        for reference in parser.assets:
            assert reference.startswith(root_path + "/static/")
            resolved = urlsplit(urljoin(str(response.url), reference))
            assert (resolved.scheme, resolved.netloc) == ("https", "127.0.0.1:9443")
            asset = client.get(urljoin(str(response.url), reference))
            assert asset.status_code == 200
            expected = {".css": "text/css", ".js": "javascript", ".svg": "image/svg+xml", ".wav": "audio/"}
            assert expected[Path(resolved.path).suffix] in asset.headers["content-type"]
