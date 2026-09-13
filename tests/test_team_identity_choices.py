"""Synthetic duplicate-name selection, grant receipts and unchanged authorization."""
from html.parser import HTMLParser

from fastapi.testclient import TestClient
import pytest

from tests.test_browser_local_accounts import ORIGIN, PASSWORD, configured_app, csrf, login


class PersonChoices(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.pickers = []
        self.current = None
        self.option = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select" and attrs.get("name") == "principal_id":
            self.current = {"attrs": attrs, "options": []}
            self.pickers.append(self.current)
        elif tag == "option" and self.current is not None:
            self.option = {"attrs": attrs, "text": ""}
            self.current["options"].append(self.option)

    def handle_data(self, data):
        if self.option is not None:
            self.option["text"] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self.option = None
        elif tag == "select":
            self.current = None


@pytest.mark.parametrize("grant_kind", ["direct", "group"])
@pytest.mark.parametrize("long_identities", [False, True])
def test_explicit_duplicate_name_choice_grants_only_selected_account(tmp_path, grant_kind, long_identities):
    app, repo = configured_app(tmp_path)
    first_username = "first." + "r" * 122 if long_identities else "first.reviewer"
    second_username = "second." + "r" * 121 if long_identities else "second.reviewer"
    display_name = "Synthetic Reviewer".ljust(160, "R") if long_identities else "Synthetic Reviewer"
    with TestClient(app, base_url=ORIGIN) as admin, TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        login(admin)
        for username, client in ((first_username, first), (second_username, second)):
            response = admin.post("/admin/people/create", data={"csrf_token": csrf(admin),
                "username": username, "display_name": display_name, "password": PASSWORD,
                "password_confirm": PASSWORD, "role": "reviewer"}, follow_redirects=False)
            assert response.status_code == 303
            assert login(client, username).status_code == 303
        response = admin.post("/matters", data={"csrf_token": csrf(admin), "name": "Synthetic identity choice"}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        setup = f"/matters/{slug}/setup"
        store = app.state.workbench.workspace
        matter = store.all_matters()[0]
        principals = {person.login_name: person for person in store.active_principals()}
        group = None
        if grant_kind == "group":
            assert admin.post("/admin/groups", data={"csrf_token": csrf(admin), "name": "Synthetic team"}).status_code == 200
            group = store.team_groups()[0]["group_id"]
            assert admin.post(f"/matters/{slug}/groups", data={"csrf_token": csrf(admin), "group_id": group}).status_code == 200
        picker_url = "/admin/groups" if group else setup
        add_url = f"/admin/groups/{group}/members" if group else f"/matters/{slug}/members"
        picker = PersonChoices(admin.get(picker_url).text).pickers[0]
        assert "required" in picker["attrs"]
        placeholder = picker["options"][0]
        assert placeholder["attrs"]["value"] == ""
        assert "selected" in placeholder["attrs"] and "disabled" in placeholder["attrs"]
        assert placeholder["text"] == "Choose a person"
        options = [option for option in picker["options"] if option["attrs"]["value"]
                   in {principals[first_username].principal_id, principals[second_username].principal_id}]
        assert {option["text"] for option in options} == {
            f"{display_name} ({first_username})", f"{display_name} ({second_username})"}
        # Choosing the second named candidate must not grant the first candidate.
        selected = options[1]
        username = next(name for name, person in principals.items() if person.principal_id == selected["attrs"]["value"])
        granted, denied = (first, second) if username == first_username else (second, first)
        empty = admin.post(add_url, data={"csrf_token": csrf(admin), "principal_id": ""})
        assert empty.status_code in {403, 422}
        assert first.get(f"/matters/{slug}/home").status_code == 404
        assert second.get(f"/matters/{slug}/home").status_code == 404
        response = admin.post(add_url, data={"csrf_token": csrf(admin), "principal_id": selected["attrs"]["value"]})
        assert response.status_code == 200
        assert selected["text"] + " added to the " in response.text
        assert f"<strong>{selected['text']}</strong>" in response.text
        assert f"<strong>{selected['text']}</strong>" in admin.get(setup).text
        assert granted.get(f"/matters/{slug}/home").status_code == 200
        assert denied.get(f"/matters/{slug}/home").status_code == 404
        assert denied.get(f"/matters/{slug}/notebook/export?format=markdown").status_code == 404
        remove_url = (f"/admin/groups/{group}/members/{selected['attrs']['value']}/remove" if group
                      else f"/matters/{slug}/members/{selected['attrs']['value']}/remove")
        removed = admin.post(remove_url, data={"csrf_token": csrf(admin)})
        assert removed.status_code == 200 and selected["text"] in removed.text
        assert granted.get(f"/matters/{slug}/home").status_code == 404
        assert granted.get(f"/matters/{slug}/notebook/export?format=markdown").status_code == 404
        assert len(store.members(matter.matter_id)) == 1
