import json
import html
import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from case_intelligence.exact_search_results import (
    ExactSearchChanged, ExactSearchUnavailable, ExactScanPolicy,
    ReferenceExactSearchBackend, search_documents,
    build_search_query, passage_preview,
)
from case_intelligence.pilot_uploads import PilotDocument
from case_intelligence.workbench import create_workbench_app


def document(index, *texts, state="ready", name=None):
    return PilotDocument(
        document_id=f"{index:032x}", display_name=name or f"Synthetic {index:04}.txt",
        stored_name="", media_type="text/plain", size=0, state=state, message="",
        units=[{"number": n, "text": text} for n, text in enumerate(texts, 1)],
        version_id=f"version-{index}",
    )


def scan(documents, query="red", **kwargs):
    return search_documents(documents, query, scope=("synthetic-matter", "", ""), **kwargs)


def test_complete_population_and_stable_pagination_beyond_ranked_limits():
    documents = [document(n, "red bicycle") for n in range(137)]
    documents += [document(200, "red", "blue"), document(201, "red", state="processing"), document(202, "")]
    first = scan(reversed(documents), "red NOT blue")
    assert first.total == 137 and first.population == 140 and first.eligible == 138
    assert first.exclusions == {"Not ready": 1, "No searchable text": 1}
    found = []
    for page in range(1, first.pages + 1):
        result = scan(documents, "red NOT blue", page=page, expected_fingerprint=first.fingerprint)
        assert result.total == 137
        found.extend(item.document_id for item in result.items)
    assert found == [item.document_id for item in documents[:137]]
    assert len(set(found)) == 137


def test_document_scope_phrases_negation_and_explanations():
    documents = [document(1, "red", "bicycle"), document(2, "red bicycle", "blue"), document(3, "red bicycle")]
    assert scan(documents, "red AND bicycle").total == 3
    result = scan(documents, '"red bicycle" NOT blue')
    assert [item.document_id for item in result.items] == [documents[2].document_id]
    assert result.items[0].matching_unit_count == 1
    assert scan([document(4, "neutral")], "NOT red").items[0].passages == ()


@pytest.mark.parametrize("change", ["text", "version", "state", "name", "membership"])
def test_source_mutation_rejects_old_page(change):
    documents = [document(1, "red")]
    first = scan(documents)
    if change == "text":
        documents[0].units[0]["text"] = "blue"
    elif change == "version":
        documents[0].version_id = "replacement"
    elif change == "state":
        documents[0].state = "processing"
    elif change == "name":
        documents[0].display_name = "renamed.txt"
    else:
        documents.append(document(2, "red"))
    with pytest.raises(ExactSearchChanged):
        scan(documents, expected_fingerprint=first.fingerprint)


@pytest.mark.parametrize("limits", [{"max_documents": 1}, {"max_characters": 1}, {"max_seconds": -1}])
def test_budget_failure_never_returns_partial_results_or_exact_total(limits):
    with pytest.raises(ExactSearchUnavailable, match="No exact total or partial results"):
        scan([document(1, "red"), document(2, "red")], **limits)


def test_reference_backend_uses_configurable_product_policy():
    backend = ReferenceExactSearchBackend(ExactScanPolicy(max_documents=1))
    with pytest.raises(ExactSearchUnavailable):
        backend.search([document(1, "red"), document(2, "red")], "red", scope=("synthetic",))


def test_frozen_known_answer_corpus_runs_through_result_service():
    corpus = json.loads((Path(__file__).parent / "fixtures/synthetic/product-foundation/v1/corpus.json").read_text())
    documents = []
    for index, item in enumerate(corpus["documents"]):
        if item["matter_id"] == corpus["matter_id"]:
            source = document(index, *(unit["text"] for unit in item["units"]), state=item["state"])
            source.document_id = item["document_id"]
            documents.append(source)
    for case in corpus["exact_search_cases"]:
        assert {item.document_id for item in scan(documents, case["query"]).items} == set(case["expected_document_ids"])


def test_route_authorizes_before_scan_and_never_uses_ranked_retriever(tmp_path, monkeypatch):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        response = client.post("/matters", data={"name": "Synthetic exact matter", "descriptor": "Synthetic"}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        bench = app.state.workbench
        matter = bench.matter(slug, "development-taylor-morgan")
        store = bench.source_store(matter)
        sources = [document(n, "red bicycle") for n in range(31)]
        sources.append(document(40, "red", state="processing"))
        store.documents.update({item.document_id: item for item in sources})
        bench.workspace.reconcile_source_organizations(matter.matter_id,
            tuple((item.document_id, "upload", item.display_name) for item in sources))
        selected = bench.workspace.create_source_set(matter.matter_id, "Synthetic subset",
            [sources[0].document_id], matter.owner_id)
        collection = bench.workspace.create_source_collection(matter.matter_id,
            "Synthetic collection", "upload", matter.owner_id)
        bench.workspace.move_sources_to_collection(matter.matter_id,
            [sources[1].document_id], collection.collection_id, matter.owner_id)
        outsider = bench.workspace.upsert_principal("preview", "synthetic-outsider",
            "Synthetic Outsider", "outsider@example.test")
        foreign = bench.create_matter("Synthetic foreign matter", "Synthetic canary", outsider.principal_id)
        foreign_document = document(100, "red SECRET-CANARY")
        bench.source_store(foreign).documents[foreign_document.document_id] = foreign_document
        monkeypatch.setattr(bench, "_retriever", lambda *args, **kwargs: pytest.fail("exact search called ranked retrieval"))
        result = client.get(f"/matters/{slug}/exact-search", params={"q": "red"})
        assert result.status_code == 200
        assert "31 sources found" in result.text and "1 still preparing or need attention" in result.text
        assert "Next →</a>" in result.text
        plain = client.get(f"/matters/{slug}/exact-search", params={"words": "red bicycle", "search": "1"})
        assert plain.status_code == 200 and "31 sources found" in plain.text
        assert 'value="red bicycle"' in plain.text and '<mark>red</mark>' in plain.text
        assert "open" not in re.search(r'<details class="find-advanced"([^>]*)>', plain.text).group(1)
        next_href = html.unescape(re.search(r'href="([^"]+)">Next →</a>', plain.text).group(1))
        assert "words=red+bicycle" in next_href
        assert "Page 2 of 2" in client.get(next_href).text
        empty = client.get(f"/matters/{slug}/exact-search", params={"search": "1"})
        assert empty.status_code == 400 and "Enter a name, word, or phrase" in empty.text
        advanced = client.get(f"/matters/{slug}/exact-search", params={"search": "1", "advanced": "1",
            "q": "red", "words": "missing", "source_set": selected.source_set_id})
        assert advanced.status_code == 200 and "1 source found" in advanced.text
        simple_again = client.get(f"/matters/{slug}/exact-search", params={"search": "1", "advanced": "0",
            "q": "missing", "words": "red"})
        assert simple_again.status_code == 200 and "31 sources found" in simple_again.text
        scoped = client.get(f"/matters/{slug}/exact-search", params={"q": "red", "source_set": selected.source_set_id})
        assert scoped.status_code == 200 and "1 source found" in scoped.text
        intersection = client.get(f"/matters/{slug}/exact-search", params={"q": "red",
            "source_set": selected.source_set_id, "collection": collection.collection_id})
        assert intersection.status_code == 200 and "0 sources found" in intersection.text
        assert "SECRET-CANARY" not in result.text
        assert client.get(f"/matters/{foreign.slug}/exact-search", params={"q": "red"}).status_code == 404
        assert client.get(f"/matters/{foreign.slug}/exact-search", params={"q": "red",
            "source_set": selected.source_set_id}).status_code == 404
        invalid = client.get(f"/matters/{slug}/exact-search", params={"q": "red AND"})
        assert invalid.status_code == 400 and "character" in invalid.text
        assert "0 sources found" not in invalid.text
        missing = client.get(f"/matters/{slug}/exact-search", params={"q": "red", "source_set": "missing"})
        assert missing.status_code == 404
        assert client.get("/matters/m-000000000000/exact-search", params={"q": "red"}).status_code == 404
        fingerprint = bench.exact_search(matter, "red").fingerprint
        store.documents[sources[0].document_id].units[0]["text"] = "blue"
        changed = client.get(f"/matters/{slug}/exact-search", params={"q": "red", "page": 2, "fingerprint": fingerprint})
        assert changed.status_code == 409 and "Search again" in changed.text


def test_unreadable_ready_source_invalidates_the_whole_scan():
    broken = document(2)
    broken.units_file = "synthetic-units.json"
    def fail(_):
        raise RuntimeError("synthetic unavailable source")
    broken._units_loader = fail
    with pytest.raises(ExactSearchUnavailable, match="No exact total"):
        scan([document(1, "red"), broken])


def test_matching_checks_deadline_inside_long_units(monkeypatch):
    from case_intelligence.exact_search import parse_query
    checks = 0
    def stop():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise ExactSearchUnavailable("synthetic deadline")
    with pytest.raises(ExactSearchUnavailable):
        parse_query('"red bicycle"').matches_units(["neutral " * 10000], budget_check=stop)
    assert checks == 3


def test_plain_search_fields_do_not_require_or_interpret_boolean_syntax():
    documents = [document(1, "red bicycle", "returned to the depot"),
                 document(2, "red bicycle", "cancelled"), document(3, "and or not")]
    result = scan(documents, build_search_query("red bicycle", "returned to the depot", "cancelled blue"))
    assert [item.document_id for item in result.items] == [documents[0].document_id]
    literal = scan(documents, build_search_query("AND OR NOT"))
    assert [item.document_id for item in literal.items] == [documents[2].document_id]
    assert scan(documents, build_search_query(exclude="cancelled")).total == 2


def test_preview_finds_late_words_preserves_text_and_keeps_markup_inert():
    from case_intelligence.exact_search import parse_query
    unit = document(1, "neutral " * 100 + '<script>depot</script> nearby').parsed_units()[0]
    preview = passage_preview(unit, parse_query("depot"))
    text = "".join(piece for piece, _ in preview["pieces"])
    assert '<script>depot</script>' in text
    assert ("depot", True) in preview["pieces"]
    assert text.startswith("…")


def test_scan_releases_workspace_lock_after_capturing_scope(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        response = client.post("/matters", data={"name": "Synthetic concurrent search", "descriptor": ""}, follow_redirects=False)
        bench = app.state.workbench
        matter = bench.matter(response.headers["location"].split("/")[2], "development-taylor-morgan")
        entered, release, workspace_read = threading.Event(), threading.Event(), threading.Event()
        errors = []

        class PausingBackend:
            def search(self, documents, query, **kwargs):
                entered.set()
                assert release.wait(5)
                return ReferenceExactSearchBackend().search(documents, query, **kwargs)

        bench.exact_search_backend = PausingBackend()
        def search():
            try:
                bench.exact_search(matter, "red")
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=search)
        reader = threading.Thread(target=lambda: (bench.workspace.source_sets(matter.matter_id), workspace_read.set()))
        worker.start()
        try:
            assert entered.wait(2)
            reader.start()
            assert workspace_read.wait(2), "Text matching blocked the global workspace lock"
        finally:
            release.set()
            worker.join(5)
            if reader.ident is not None:
                reader.join(5)
        assert not errors


def test_phrase_preview_anchors_on_complete_phrase_and_preserves_unicode():
    from case_intelligence.exact_search import parse_query
    for prefix, phrase in [("red", "red bicycle"), ("cafe\u0301", "cafe\u0301 bicycle"), ("İ", "İ bicycle")]:
        unit = document(1, prefix + " isolated. " + "neutral " * 100 + phrase + " nearby").parsed_units()[0]
        preview = passage_preview(unit, parse_query('"' + phrase + '"'))
        text = "".join(piece for piece, _ in preview["pieces"])
        assert phrase in text and "isolated" not in text
        assert (phrase, True) in preview["pieces"]


def test_skipped_pdf_pages_link_to_matching_extracted_unit_position(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        response = client.post("/matters", data={"name": "Synthetic skipped page", "descriptor": ""}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        bench = app.state.workbench
        matter = bench.matter(slug, "development-taylor-morgan")
        source = document(1, "opening", "target bicycle", "following extracted page")
        source.units[1]["number"] = 3
        source.units[2]["number"] = 4
        bench.source_store(matter).documents[source.document_id] = source
        result = bench.exact_search(matter, "bicycle")
        assert result.items[0].passages[0].number == 3
        assert result.items[0].passage_positions == (2,)
        page = client.get(f"/matters/{slug}/exact-search", params={"words": "bicycle"})
        match = re.search(r'<a class="find-location" href="([^"]+)">', page.text)
        assert match and match.group(1).endswith("?unit=2")


def test_advanced_form_keyboard_submission_has_its_own_explicit_mode(tmp_path):
    from html.parser import HTMLParser
    class FormParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms = {}
            self.active = None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                assert self.active is None, "Forms must not be nested"
                self.active = {**attrs, "inputs": []}
                self.forms[attrs.get("id")] = self.active
            elif tag == "input" and self.active is not None:
                self.active["inputs"].append(attrs)
        def handle_endtag(self, tag):
            if tag == "form":
                self.active = None
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        response = client.post("/matters", data={"name": "Synthetic expression keyboard", "descriptor": ""}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        bench = app.state.workbench
        matter = bench.matter(slug, "development-taylor-morgan")
        source = document(1, "red bicycle")
        bench.source_store(matter).documents[source.document_id] = source
        page = client.get(f"/matters/{slug}/exact-search", params={"words": "missing"})
        parser = FormParser()
        parser.feed(page.text)
        expression = parser.forms["find-expression-form"]
        assert any(item.get("id") == "find-query" for item in expression["inputs"])
        assert expression["id"] == "find-expression-form"
        # Enter submits successful controls without requiring a clicked button.
        params = {item["name"]: item.get("value", "") for item in expression["inputs"]}
        params["q"] = "red AND bicycle"
        result = client.get(expression["action"], params=params)
        assert result.status_code == 200 and "1 source found" in result.text
        assert "words" not in params and params["advanced"] == "1"


def test_boolean_preview_uses_only_a_satisfied_branch_even_after_many_false_starts():
    source = document(1, "red", "red again", "red once more", "green explains this match")
    result = scan([source], "(red AND bicycle) OR green")
    assert result.total == 1 and result.items[0].matching_unit_count == 1
    assert result.items[0].passage_positions == (4,)
    assert result.items[0].previews[0]["pieces"][1] == ("green", True)
    source = document(2, "red isolated. " + "neutral " * 120 + "green")
    preview = scan([source], "(red AND bicycle) OR green").items[0].previews[0]
    assert "isolated" not in "".join(text for text, _ in preview["pieces"])
    assert ("green", True) in preview["pieces"]


def test_partial_pdf_coverage_is_excluded_including_negation_and_invalidates_old_pages():
    partial = document(1, "red")
    partial.media_type, partial.page_count = "application/pdf", 2
    partial.message = "1 of 2 pages ready and searchable; 1 page needs OCR"
    complete = document(2, "red", "neutral")
    complete.media_type, complete.page_count = "application/pdf", 2
    for query in ("red", "red NOT blue", "NOT blue"):
        result = scan([partial, complete], query)
        assert result.total == result.eligible == 1 and result.population == 2
        assert result.exclusions == {"Incomplete page coverage": 1}
        assert result.items[0].document_id == complete.document_id
    previous = scan([complete])
    complete.page_count = 3
    with pytest.raises(ExactSearchChanged):
        scan([complete], expected_fingerprint=previous.fingerprint)
    complete.page_count = 0
    assert scan([complete]).exclusions == {"Incomplete page coverage": 1}


def test_preview_work_consumes_the_same_search_deadline(monkeypatch):
    import case_intelligence.exact_search_results as module
    original_preview = module.passage_preview
    clock = {"preview": False, "checks": 0}
    def monotonic():
        if clock["preview"]:
            clock["checks"] += 1
            return clock["checks"] * .25
        return 0
    def preview(*args, **kwargs):
        clock["preview"] = True
        return original_preview(*args, **kwargs)
    monkeypatch.setattr(module.time, "monotonic", monotonic)
    monkeypatch.setattr(module, "passage_preview", preview)
    source = document(1, "term0 " + "neutral " * 20000)
    query = " OR ".join(f"term{index}" for index in range(40))
    with pytest.raises(ExactSearchUnavailable, match="No exact total or partial results"):
        scan([source], query, max_seconds=1)
    assert clock["preview"] and clock["checks"] == 5


def test_media_timestamp_links_and_partial_page_warning_are_visible(tmp_path):
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        response = client.post("/matters", data={"name": "Synthetic transcript locator", "descriptor": ""}, follow_redirects=False)
        slug = response.headers["location"].split("/")[2]
        bench = app.state.workbench
        matter = bench.matter(slug, "development-taylor-morgan")
        media = document(1, "opening", "red bicycle appears at this moment")
        media.media_type = "audio/wav"
        media.units[0].update(start_ms=0, end_ms=1000, location_label="0:00–0:01")
        media.units[1].update(start_ms=45000, end_ms=46000, location_label="0:45–0:46")
        partial = document(2, "red")
        partial.media_type, partial.page_count = "application/pdf", 2
        bench.source_store(matter).documents.update({item.document_id: item for item in (media, partial)})
        result = client.get(f"/matters/{slug}/exact-search", params={"words": "red"})
        assert result.status_code == 200 and "1 source found" in result.text
        assert "have incomplete page coverage and were left out" in result.text
        match = re.search(r'<a class="find-location" href="([^"]+)">', result.text)
        assert match and match.group(1).endswith("?start_ms=45000#segment-2")


def test_boolean_preview_diversifies_support_for_each_required_positive_term():
    source = document(1, "red", "red again", "red once more", "bicycle")
    item = scan([source], "red AND bicycle").items[0]
    assert item.passage_positions[:2] == (1, 4)
    assert item.matching_unit_count == 4


def test_concurrent_exact_requests_are_rejected_before_worker_dispatch(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    app = create_workbench_app(tmp_path / "runtime", auth_mode="test")
    with TestClient(app) as client:
        created = client.post("/matters", data={"name": "Synthetic admission", "descriptor": ""}, follow_redirects=False)
        slug = created.headers["location"].split("/")[2]
        entered, release = threading.Event(), threading.Event()
        bench = app.state.workbench
        original = bench.exact_search
        calls = []
        def blocked(*args, **kwargs):
            calls.append(1)
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)
        monkeypatch.setattr(bench, "exact_search", blocked)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.get, f"/matters/{slug}/exact-search?q=red")
            assert entered.wait(3)
            try:
                for _ in range(8):
                    rejected = client.get(f"/matters/{slug}/exact-search?q=red")
                    assert rejected.status_code == 429
                    assert rejected.headers["Retry-After"] == "1"
                assert client.get("/health").status_code == 200
                assert len(calls) == 1 and not first.done()
            finally:
                release.set()
            assert first.result(timeout=3).status_code == 200
        assert client.get(f"/matters/{slug}/exact-search?q=red").status_code == 200
        assert len(calls) == 2
