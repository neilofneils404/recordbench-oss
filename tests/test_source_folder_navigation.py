"""Synthetic precise subtree browsing; original source paths remain unchanged."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app
from tests.test_source_library import ACTOR, _matter


def test_folder_filter_selects_only_its_exact_subtree(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    paths = (
        'Production/North/report.txt',
        'Production/North/Interviews/detail.txt',
        'Production/Northwest/report.txt',
        'Other/North/report.txt',
        'Production/North-reference.txt',
    )
    with TestClient(app) as client:
        slug = _matter(client, 'Generated folder navigation')
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        sources = tuple(SimpleNamespace(relative_path=path, display_name=path.rsplit('/', 1)[-1],
            media_type='text/plain', byte_size=64, stable_device=1, stable_inode=index+1,
            stable_mtime_ns=1_700_000_000_000_000_000+index) for index, path in enumerate(paths))
        bench.source_store(matter).register_linked_sources(
            source_location_id='generated-folder-navigation', sources=sources)
        page = client.get(f'/matters/{slug}/setup', params={'view': 'list', 'folder': 'Production/North'})
        assert page.status_code == 200
        assert page.text.count('name="selected"') == 2
        assert 'Production/Northwest' not in page.text and 'Other/North' not in page.text
        assert 'North-reference.txt' not in page.text
        assert 'data-source-folder-nav' in page.text


def _register(bench, matter, paths):
    store = bench.source_store(matter)
    sources = tuple(SimpleNamespace(relative_path=path, display_name=path.rsplit('/', 1)[-1],
        media_type='text/plain', byte_size=64, stable_device=1, stable_inode=index+1,
        stable_mtime_ns=1_700_000_000_000_000_000+index) for index, path in enumerate(paths))
    store.register_linked_sources(source_location_id='generated-folder-navigation', sources=sources)
    bench._ensure_source_organizations(matter, store)
    return {item.relative_path: item for item in store.documents.values()}


def test_folder_names_are_literal_and_unicode_normalized(tmp_path):
    import unicodedata
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        paths = ['100%_ready/quoted\'folder/report.txt', '100XXready/other.txt',
            'Café/证据/detail.txt', 'Cafeteria/other.txt', 'At root.txt']
        _register(bench, matter, paths)
        for folder, expected in [("100%_ready/quoted'folder", paths[0]),
                (unicodedata.normalize('NFD', 'Café/证据'), paths[2])]:
            result = bench.source_library(matter, folder=folder)
            assert result.total == 1 and result.items[0].relative_path == expected
        root = bench.workspace.source_catalog_folders(matter.matter_id)
        assert {item.name for item in root.items} == {'100%_ready', '100XXready', 'Café', 'Cafeteria'}
        assert all(item.source_count == 1 for item in root.items)
        page = client.get(f'/matters/{slug}/setup', params={'folder': "100%_ready/quoted'folder"})
        assert page.status_code == 200 and page.text.count('name="selected"') == 1
        assert 'quoted&#39;folder' in page.text


def test_folder_source_pages_and_child_pages_are_bounded_at_ten_thousand_sources(tmp_path):
    import re
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        _register(bench, matter, [f'Production {i // 100:03d}/records/row-{i:05d}.txt' for i in range(10_000)])
        def forbidden(*_args):
            raise AssertionError('Folder browsing must use bounded catalog projections')
        bench._source_rows = forbidden
        page = client.get(f'/matters/{slug}/setup', params={'view': 'list', 'folder_page': 2})
        assert page.status_code == 200 and 'Folder page 2 of 2' in page.text
        nav = re.search(r'<nav[^>]*data-source-folder-nav.*?</nav>', page.text, re.S).group(0)
        assert nav.count('<li>') == 50 and 'Production 050' in nav and 'Production 099' in nav
        assert 'Production 049' not in nav
        page = client.get(f'/matters/{slug}/setup', params={
            'folder': 'Production 099', 'page_size': 25, 'page': 99, 'folder_page': 99})
        assert page.text.count('name="selected"') == 25
        assert '76–100 of 100' in page.text and 'Page 4 of 4' in page.text
        assert 'records' in page.text and '100 sources' in page.text


def test_folder_views_preserve_collection_set_status_review_and_sort(tmp_path):
    import html
    import re
    from urllib.parse import parse_qs, urlsplit
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        paths = ['Production/North/a.txt', 'Production/North/b.txt', 'Production/South/c.txt', 'Other/d.txt']
        docs = _register(bench, matter, paths)
        workspace = bench.workspace
        collection = workspace.create_source_collection(matter.matter_id, 'Generated review collection', 'upload', ACTOR)
        workspace.move_sources_to_collection(matter.matter_id, [docs[paths[0]].document_id, docs[paths[1]].document_id], collection.collection_id, ACTOR)
        group = workspace.create_source_set(matter.matter_id, 'Generated review set', [docs[paths[0]].document_id, docs[paths[2]].document_id], ACTOR)
        overlap = workspace.create_source_set(matter.matter_id, 'Generated overlapping set', [docs[paths[0]].document_id], ACTOR)
        workspace.update_source_review_state(matter.matter_id, [docs[paths[0]].document_id], 'flagged', ACTOR)
        params = {'view': 'list', 'folder': 'Production', 'source_set': group.source_set_id,
            'collection': collection.collection_id, 'review': 'flagged', 'status': 'processing', 'sort': 'name_desc'}
        page = client.get(f'/matters/{slug}/setup', params=params)
        assert page.status_code == 200 and page.text.count('name="selected"') == 1
        nav = re.search(r'<nav[^>]*data-source-folder-nav.*?</nav>', page.text, re.S).group(0)
        assert 'North' in nav and 'South' not in nav and '1 source' in nav
        child = next(html.unescape(url) for url in re.findall(r'href="([^"]+)"', nav) if 'folder=Production%2FNorth' in url)
        query = parse_qs(urlsplit(child).query)
        assert all(query[key] == [value] for key, value in params.items() if key not in {'folder'})
        form = re.search(r'<form class="source-library-filters".*?</form>', page.text, re.S).group(0)
        assert f'name="source_set" value="{group.source_set_id}"' in form
        assert 'name="folder" value="Production"' in form and 'name="status" value="processing"' in form
        assert workspace.source_set(matter.matter_id, overlap.source_set_id).source_count == 1
        assert workspace.source_set(matter.matter_id, group.source_set_id).source_count == 2
        assert docs[paths[0]].relative_path == paths[0]


def test_unknown_removed_and_foreign_folders_cannot_broaden_the_source_view(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        docs = _register(bench, matter, ['Shared/own.txt'])
        workspace = bench.workspace
        other = 'generated-foreign-owner'
        workspace.upsert_principal('test', other, 'Generated foreign owner', other, preferred_principal_id=other)
        foreign = bench.create_matter('Generated foreign folder', '', other)
        _register(bench, foreign, ['Shared/FOREIGN-CANARY.txt', 'Foreign-only/hidden.txt'])
        page = client.get(f'/matters/{slug}/setup', params={'folder': 'Shared'})
        assert page.text.count('name="selected"') == 1 and 'FOREIGN-CANARY' not in page.text
        workspace.delete_source_catalog(matter.matter_id, (docs['Shared/own.txt'].document_id,))
        for folder in ['Shared', 'Unknown', 'Foreign-only']:
            page = client.get(f'/matters/{slug}/setup', params={'folder': folder})
            assert page.status_code == 200 and page.text.count('name="selected"') == 0
            assert 'Up one folder' in page.text and 'FOREIGN-CANARY' not in page.text
        assert client.get(f'/matters/{foreign.slug}/setup', params={'folder': 'Shared'}).status_code == 404


def test_malformed_folder_requests_fail_with_a_generic_recovery_message(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        for folder in ['../outside', '/absolute', 'C:\\generated', 'double//slash', 'trailing/',
                'control\x00name', 'hidden\u202ename', 'Folder/CON', 'folder.']:
            page = client.get(f'/matters/{slug}/setup', params={'folder': folder})
            assert page.status_code == 400 and page.json()['detail'] == 'Choose a listed source folder.'
