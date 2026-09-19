"""Rendered source-library semantics and one set of controls across layouts."""

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app
from tests.test_source_folder_navigation import _register
from tests.test_source_library import ACTOR, _matter


@dataclass
class Element:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)
    text: str = ""
    parent: "Element | None" = None


class RenderedHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.stack = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        element = Element(tag, dict(attrs), parent=parent)
        self.elements.append(element)
        if parent:
            parent.children.append(element)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        for element in self.stack:
            element.text += text

    def matching(self, **attrs):
        return [element for element in self.elements if all(element.attrs.get(key) == value for key, value in attrs.items())]


def test_bulk_fields_keep_real_labels_and_page_selection_outside_clipped_headers(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(),
        auth_mode="test", background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        documents = _register(bench, matter, ["Synthetic/First.txt"])
        bench.workspace.create_source_set(matter.matter_id, "Synthetic selection",
            [next(iter(documents.values())).document_id], ACTOR)
        response = client.get(f"/matters/{slug}/setup?view=list")
        assert response.status_code == 200
        page = RenderedHTML(response.text)
        for name, label_text in {
            "action": "Bulk action",
            "collection_id": "Destination collection",
            "source_set_id": "Source set",
            "source_set_name": "New source set name",
        }.items():
            controls = page.matching(name=name)
            assert len(controls) == 1
            control = controls[0]
            label = control.parent
            assert label.tag == "label" and label.attrs["for"] == control.attrs["id"]
            assert label.children[0].tag == "span" and label.children[0].text == label_text
            assert "visually-hidden" not in label.attrs.get("class", "")
            assert "hidden" not in label.attrs and label.attrs.get("aria-hidden") != "true"
            assert label.parent.attrs.get("id") == "source-bulk-form"
        select_all = [element for element in page.elements if "data-source-select-all" in element.attrs]
        assert len(select_all) == 1
        assert select_all[0].parent.tag == "label"
        assert "Select page" in select_all[0].parent.text
        assert select_all[0].parent.parent.parent.attrs["id"] == "source-bulk-form"


def test_reflowed_source_rows_keep_headers_identity_single_selection_and_return_context(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(),
        auth_mode="test", background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        names = ["Synthetic-" + "longfilename" * 7 + "-résumé.txt", "Second.txt"]
        _register(bench, matter, [f"Production/Records/{name}" for name in names])
        context = dict(view="list", folder="Production/Records", kind="TXT", status="processing",
            review="unreviewed", sort="name", page_size="25", page="1")
        response = client.get(f"/matters/{slug}/setup", params=context)
        assert response.status_code == 200
        page = RenderedHTML(response.text)
        table = page.matching(role="table", **{"aria-label": "Matter sources"})[0]
        assert table.attrs["aria-colcount"] == "6"
        header, *rows = table.children
        assert [cell.text.strip() for cell in header.children] == [
            "Select source", "Source", "Collection", "Review and status", "Length", "Actions"]
        assert all(cell.attrs.get("role") == "columnheader" for cell in header.children)
        assert "hidden" not in header.attrs and header.attrs.get("aria-hidden") != "true"
        assert len(rows) == len(names)
        assert len(page.matching(name="selected")) == len(names)
        for row in rows:
            assert row.attrs["role"] == "row"
            assert len(row.children) == 6
            assert all(cell.attrs.get("role") == "cell" for cell in row.children)
            selection, identity, collection, status, length, actions = row.children
            name = identity.children[1].children[0]
            assert name.text.rsplit("/", 1)[-1] in names
            assert "Unreviewed" in status.text and status.text.strip() != "Unreviewed"
            assert "Collection" in collection.text and "Length" in length.text
            checkbox = selection.children[0].children[0]
            assert checkbox.attrs["aria-label"] == f"Select {name.text}"
            assert checkbox.attrs["form"] == "source-bulk-form"
            open_link = actions.children[0]
            assert open_link.attrs["aria-describedby"] == name.attrs["id"]
            assert checkbox.attrs["value"] in urlsplit(open_link.attrs["href"]).path
            returned_context = parse_qs(parse_qs(urlsplit(open_link.attrs["href"]).query)["browse"][0])
            assert all(returned_context[key] == [value] for key, value in context.items())
            assert identity.children[1].attrs["href"] == open_link.attrs["href"]


def test_empty_source_library_keeps_a_named_table_cell(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", generator=UnavailableGenerator(),
        auth_mode="test", background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        page = RenderedHTML(client.get(f"/matters/{slug}/setup?view=list").text)
        table = page.matching(role="table", **{"aria-label": "Matter sources"})[0]
        empty = table.children[-1]
        assert empty.attrs["role"] == "row"
        assert empty.children[0].attrs == {"role": "cell", "aria-colspan": "6"}
        assert "Selected records will appear here" in empty.text
