from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.identity import LocalAccountSettings
from case_intelligence.workbench import create_workbench_app
from tests.test_browser_local_accounts import ORIGIN, configured_app, create, csrf, login
from tests.test_processing_awareness import _catalog_source


def test_setup_progress_uses_sources_membership_and_latest_grant_access(tmp_path):
    app, repo = configured_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as admin:
        assert login(admin).headers["location"] == "/admin/setup"
        page = admin.get("/admin/setup")
        assert "Bring your team into RecordBench" in page.text
        assert "No active matter in your case team" in page.text
        assert "temporarily unavailable" in page.text
        assert create(admin, "first.reviewer").status_code == 303
        assert create(admin, "second.reviewer").status_code == 303
        first, second = TestClient(app, base_url=ORIGIN), TestClient(app, base_url=ORIGIN)
        login(first, "first.reviewer")
        login(second, "second.reviewer")
        assert first.get("/admin/setup").status_code == 403
        assert "Another eligible person has signed in" in admin.get("/admin/setup").text
        response = admin.post("/matters", data={"csrf_token": csrf(admin), "name": "Synthetic onboarding matter"}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        workspace = app.state.workbench.workspace
        matter = workspace.all_matters()[0]
        workspace.upsert_source_catalog(matter.matter_id, [_catalog_source("a" * 32, tone="ready", state="ready")])
        page = admin.get("/admin/setup", params={"matter": slug})
        assert "1 of 1 sources are searchable" in page.text
        assert f'/matters/{slug}/setup#case-team-heading' in page.text
        principal = next(p for p in workspace.active_principals() if p.provider_subject == "first.reviewer")
        admin.post(f"/matters/{slug}/members", data={"csrf_token": csrf(admin), "principal_id": principal.principal_id})
        assert "Waiting for a current teammate to open" in admin.get("/admin/setup").text
        assert second.get(f"/matters/{slug}/home").status_code == 404
        assert first.get(f"/matters/{slug}/home").status_code == 200
        assert "A current teammate has opened this matter" in admin.get("/admin/setup").text
        admin.post(f"/matters/{slug}/members/{principal.principal_id}/remove", data={"csrf_token": csrf(admin)})
        admin.post(f"/matters/{slug}/members", data={"csrf_token": csrf(admin), "principal_id": principal.principal_id})
        assert "Waiting for a current teammate to open" in admin.get("/admin/setup").text
        first.close()
        second.close()
    # A restart reconciles this synthetic projection, which has no stored source.
    # Team progress remains derived from persisted grants and access events.
    restarted = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="local",
        secure_cookie=True, local_settings=LocalAccountSettings(repo.path, management_root=repo.path.parent), learned_retrieval=False, answer_workers=1)
    with TestClient(restarted, base_url=ORIGIN) as admin:
        login(admin)
        page = admin.get("/admin/setup", params={"matter": slug})
        assert "0 of 0 sources are searchable" in page.text
        assert "Another eligible person is on this case team" in page.text
        assert "Waiting for a current teammate to open" in page.text


def test_oidc_setup_explains_provider_admission_and_matter_access(tmp_path):
    from tests.test_oidc_authentication import _settings, _begin, FakeOidcProvider
    settings = _settings(allowed_groups=frozenset({"review-users"}), administrator_groups=frozenset({"review-administrators"}))
    provider = FakeOidcProvider(settings)
    provider.groups = ["review-users", "review-administrators"]
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="oidc", secure_cookie=True,
        oidc_settings=settings, oidc_client=provider, learned_retrieval=False, answer_workers=1)
    with TestClient(app, base_url=settings.external_origin) as client:
        state = _begin(client, "/")
        response = client.get("/auth/oidc/callback", params={"code": "synthetic-administrator", "state": state})
        assert response.url.path == "/admin/setup"
        assert "sign-in provider manages accounts, admission groups and administrator roles" in response.text
        assert "Application administrator access and matter-team membership are separate" in response.text
        assert "Windows directory manages" not in response.text


def test_kerberos_setup_keeps_trusted_proxy_and_directory_copy(tmp_path):
    from tests.test_kerberos_authentication import _settings, _profile, _headers, REVIEWER_PRINCIPAL
    settings = replace(_settings(), administrator_principals=frozenset({REVIEWER_PRINCIPAL.casefold()}))
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(), auth_mode="kerberos", secure_cookie=True,
        kerberos_settings=settings, kerberos_profile_resolver=_profile, learned_retrieval=False, answer_workers=1)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/admin/setup").status_code == 401
        response = client.get("/auth/login", headers=_headers(), params={"next": "/"})
        assert response.url.path == "/admin/setup"
        assert "Windows directory manages accounts, admission groups and administrator groups" in response.text
        assert "Directory admission does not grant matter access" in response.text
