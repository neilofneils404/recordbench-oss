from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from case_intelligence.branding import PRODUCT_NAME, PRODUCT_TAGLINE
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app


TEMPLATES = Path(__file__).parents[1] / "src/case_intelligence/templates"


def test_recordbench_identity_is_consistent_across_health_login_and_mark(tmp_path) -> None:
    assert PRODUCT_NAME == "RecordBench"
    assert PRODUCT_TAGLINE == "Review the record. Build the work."

    with TestClient(
        create_workbench_app(
            tmp_path / "runtime",
            generator=UnavailableGenerator(),
            auth_mode="preview",
        )
    ) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["product"] == PRODUCT_NAME

        login = client.get("/auth/login")
        assert login.status_code == 200
        assert f"Sign in · {PRODUCT_NAME}" in login.text
        assert PRODUCT_TAGLINE in login.text
        assert 'class="login-brand-mark"' in login.text
        assert "Choose a preview identity" in login.text
        assert "Temporary evaluation access" in login.text
        assert "Choosing a synthetic identity is not authentication" in login.text
        assert "loopback preview" not in login.text
        assert "Case Intelligence" not in login.text

        mark = client.get("/static/favicon.svg")
        assert mark.status_code == 200
        root = ElementTree.fromstring(mark.content)
        assert root.tag.endswith("svg")
        assert PRODUCT_NAME in mark.text
        assert "#071a3c" in mark.text
        assert "#ed4b2f" in mark.text

    for path in TEMPLATES.glob("workbench_*.html"):
        text = path.read_text(encoding="utf-8")
        if "{% block title %}" in text:
            title = text.split("{% block title %}", 1)[1].split("{% endblock %}", 1)[0]
            assert "product_name" in title, path.name
