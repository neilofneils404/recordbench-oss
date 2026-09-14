"""Synthetic continuous inspection uses precisely the existing library order."""
import html
import io
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app
from tests.test_source_folder_navigation import _register
from tests.test_source_library import ACTOR, _matter


def links(text):
    return [html.unescape(value) for value in re.findall(r'href="([^"]+)"', text)]


def sidebar(text):
    return re.search(r'<aside class="source-browser".*?</aside>', text, re.S).group()


@pytest.mark.parametrize('return_kind', ['search', 'external', 'foreign'])
def test_search_return_survives_source_list_and_review_actions(tmp_path, return_kind):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        for name in ('First.txt', 'Second.txt'):
            store.store_stream(name, 'text/plain', io.BytesIO(b'A synthetic amber bicycle.'))
        results = client.get(f'/matters/{slug}/exact-search?words=amber')
        hit = html.unescape(re.search(r'class="find-open-source" href="([^"]+)"', results.text)[1])
        origin = parse_qs(urlsplit(hit).query)['entity_return_to'][0]
        if return_kind != 'search':
            origin = 'https://example.com/' if return_kind == 'external' else '/matters/another/exact-search'
        opened = client.get(urlsplit(hit).path, params={'entity_return_to': origin, 'browse': 'sort=name'})
        expected = [origin] if return_kind == 'search' else []
        source_links = [url for url in links(sidebar(opened.text)) if '/sources/' in urlsplit(url).path]
        assert len(source_links) == 2
        sequence = re.search(r'<nav class="review-sequence".*?</nav>', opened.text, re.S)[0]
        for url in source_links + links(sequence):
            assert parse_qs(urlsplit(url).query).get('entity_return_to', []) == expected
            page = client.get(url)
            assert ('Return to review context' in page.text) == bool(expected)
        for suffix, data in [('review-state', {'state': 'flagged'}), ('review-next', {})]:
            action = html.unescape(re.search(r'action="([^"]+/' + suffix + r'[^\"]*)"', opened.text)[1])
            response = client.post(action, data=data, follow_redirects=False)
            assert response.status_code == 303
            assert parse_qs(urlsplit(response.headers['location']).query).get('entity_return_to', []) == expected
        last = client.get(source_links[-1])
        action = html.unescape(re.search(r'action="([^"]+/review-next[^"]*)"', last.text)[1])
        completed = client.post(action, follow_redirects=False)
        assert completed.status_code == 303
        if expected:
            assert completed.headers['location'] == origin
        else:
            assert '/setup?' in completed.headers['location']


@pytest.mark.parametrize('sort', ['name', 'name_desc', 'oldest', 'newest', 'status'])
def test_order_and_cross_page_navigation_match_library(tmp_path, sort):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        _register(bench, matter, [f'Collection/North/Sub-{i:02d}/record.txt' for i in range(27)]
            + ['Collection/Northwest/record.txt', 'Other/record.txt'])
        def forbidden(*args):
            raise AssertionError('Do not materialize all source rows')
        bench._source_rows = forbidden
        page1 = bench.source_library(matter, view='list', folder='Collection/North', sort=sort, page_size=25)
        page2 = bench.source_library(matter, view='list', folder='Collection/North', sort=sort, page_size=25, page=2)
        context = urlencode(dict(folder='Collection/North', sort=sort, page_size=25, page=1))
        base = f'/matters/{slug}/sources/'
        opened = client.get(base + page1.items[-1].action_token, params={'browse': context})
        assert opened.status_code == 200
        assert len(re.findall('href="[^"]+/sources/', sidebar(opened.text))) == 25
        assert 'Northwest' not in sidebar(opened.text)
        next_url = links(re.search(r'<a class="review-sequence-neighbor next".*?</a>', opened.text, re.S).group())[0]
        assert page2.items[0].action_token in next_url
        next_page = client.get(next_url)
        assert 'Page 2 of 2' in sidebar(next_page.text)
        assert 'aria-current="page"' in sidebar(next_page.text)
        assert len(re.findall('href="[^"]+/sources/', sidebar(next_page.text))) == 2
        back = links(re.search(r'<a class="review-sequence-neighbor previous".*?</a>', next_page.text, re.S).group())[0]
        assert page1.items[-1].action_token in back
        assert 'Page 1 of 2' in sidebar(client.get(back).text)
        first = client.get(base + page1.items[0].action_token, params={'browse': context})
        last = client.get(base + page2.items[-1].action_token, params={'browse': context})
        assert 'previous disabled' in first.text and 'next disabled' in last.text
        assert 'Page 2 of 2' in sidebar(last.text)  # stale page number relocates active source


def test_filters_return_context_empty_view_and_mark_continue(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        docs = _register(bench, matter, ['Café/100%_batch/a.txt', 'Café/100%_batch/Sub/b.txt', 'Other/c.txt'])
        group = bench.workspace.create_source_set(matter.matter_id, 'Synthetic pair',
            [d.document_id for path, d in docs.items() if path.startswith('Café')], ACTOR)
        collection = bench.workspace.source_catalog_page(matter.matter_id).items[0].collection_id
        values = dict(view='list', folder='Café/100%_batch', source_set=group.source_set_id,
            collection=collection, status='processing', kind='TXT', review='unreviewed',
            sort='name', q='.txt', page_size=25, page=1)
        library = client.get(f'/matters/{slug}/setup', params=values)
        url = links(re.search(r'<a class="source-open-action".*?</a>', library.text, re.S).group())[0]
        opened = client.get(url)
        assert opened.status_code == 200
        panel = sidebar(opened.text)
        return_url = links(panel)[0]
        returned = parse_qs(urlsplit(return_url).query)
        assert all(returned[key] == [str(value)] for key, value in values.items())
        action = html.unescape(re.search(r'action="([^"]+/review-next[^"]*)"', opened.text).group(1))
        advanced = client.post(action, follow_redirects=False)
        assert advanced.status_code == 303
        assert docs['Café/100%_batch/Sub/b.txt'].document_id == bench.source_store(matter).get_by_action_token(urlsplit(advanced.headers['location']).path.split('/')[-1]).document_id
        assert 'browse=' in advanced.headers['location']
        assert '1 sources' in sidebar(client.get(advanced.headers['location']).text)
        state_action = html.unescape(re.search(r'action="([^"]+/review-state[^"]*)"', opened.text).group(1))
        marked = client.post(state_action, data={'state': 'flagged'}, follow_redirects=False)
        assert marked.status_code == 303 and 'browse=' in marked.headers['location']
        empty = client.get(urlsplit(url).path, params={'browse': urlencode({'folder': 'Missing'})})
        assert 'No sources match' in sidebar(empty.text)
        assert 'outside the current filters' in empty.text
        assert 'previous disabled' in empty.text and 'next disabled' in empty.text
        assert client.get(urlsplit(url).path, params={'browse': 'page=invalid'}).status_code == 400
        assert client.get(urlsplit(url).path, params={'browse': 'folder=../Other'}).status_code == 400
        foreign_slug = _matter(client, 'Synthetic separate matter')
        assert client.get(urlsplit(url).path.replace(slug, foreign_slug)).status_code == 404
        unknown = client.get(urlsplit(url).path, params={'browse': 'source_set=missing'})
        assert unknown.status_code == 404


def test_media_and_passage_links_keep_library_context(tmp_path):
    from tests.test_matter_media_workflow import ImmediateMediaProcessor, _upload_and_wait
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', media_processor=ImmediateMediaProcessor(), background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        document, token = _upload_and_wait(client, slug)
        context = urlencode(dict(kind='AUDIO', sort='name', page_size=25))
        opened = client.get(f'/matters/{slug}/sources/{token}', params={'browse': context, 'q': 'synthetic'})
        assert opened.status_code == 200
        assert 'data-media-review' in opened.text and 'data-source-browser' in opened.text
        assert 'name="browse"' in opened.text
        assert 'kind=AUDIO' in html.unescape(opened.text)
        assert 'aria-current="page"' in sidebar(opened.text)
        assert 'previous disabled' in opened.text and 'next disabled' in opened.text
        # The original serving endpoint still honors ranges and matter scoping.
        content = client.get(f'/matters/{slug}/sources/{token}/content', headers={'Range': 'bytes=0-15'})
        assert content.status_code == 206 and len(content.content) == 16
        foreign = _matter(client, 'Synthetic foreign token check')
        assert client.get(f'/matters/{foreign}/sources/{token}/content').status_code == 404


def test_transcript_filter_clear_and_pages_preserve_search_return(tmp_path):
    from tests.test_matter_media_workflow import ImmediateMediaProcessor, _upload_and_wait
    class PagedProcessor(ImmediateMediaProcessor):
        def transcript(self, owner, external_job_id):
            payload = super().transcript(owner, external_job_id)
            seed = payload['segments'][0]
            payload['segments'] = [dict(seed, id=f'synthetic-{i}', segment_id=f'synthetic-{i}',
                start=i / 100, end=(i + 1) / 100) for i in range(201)]
            return payload
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', media_processor=PagedProcessor(), background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        _, token = _upload_and_wait(client, slug)
        context = 'kind=AUDIO&sort=name'
        origin = f'/matters/{slug}/exact-search?words=red'
        path = f'/matters/{slug}/sources/{token}'
        opened = client.get(path, params={'browse': context, 'entity_return_to': origin})
        form = re.search(r'<form class="transcript-filters".*?</form>', opened.text, re.S)[0]
        fields = dict((name, html.unescape(value)) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', form))
        fields['q'] = 'red'
        assert fields['entity_return_to'] == origin
        filtered = client.get(path, params=fields)
        clear = html.unescape(re.search(r'href="([^"]+)">Clear</a>', filtered.text)[1])
        pagination = re.search(r'<nav class="source-pagination transcript-pagination".*?</nav>', filtered.text, re.S)[0]
        next_page = links(pagination)[0]
        for url in (clear, next_page):
            assert parse_qs(urlsplit(url).query)['entity_return_to'] == [origin]
            target = path + url if url.startswith('?') else url
            returned = client.get(target)
            assert returned.status_code == 200 and 'Return to review context' in returned.text
        second = client.get(path + next_page)
        previous = links(re.search(r'<nav class="source-pagination transcript-pagination".*?</nav>', second.text, re.S)[0])[0]
        assert parse_qs(urlsplit(previous).query)['entity_return_to'] == [origin]


@pytest.mark.parametrize('restrict_collection', [False, True])
def test_content_search_preserves_cross_collection_source_set(tmp_path, restrict_collection):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        docs = [store.store_stream(name, 'text/plain', io.BytesIO(b'Synthetic amber bicycle.'))[0]
                for name in ('Selected A.txt', 'Selected B.txt', 'Outside.txt')]
        bench._sync_source_catalog(matter, list(store.documents.values()))
        bench.workspace.reconcile_source_organizations(matter.matter_id,
            tuple((d.document_id, 'upload', d.display_name) for d in docs))
        first = bench.workspace.create_source_collection(matter.matter_id, 'Synthetic A', 'upload', ACTOR)
        second = bench.workspace.create_source_collection(matter.matter_id, 'Synthetic B', 'upload', ACTOR)
        bench.workspace.move_sources_to_collection(matter.matter_id, [docs[0].document_id, docs[2].document_id], first.collection_id, ACTOR)
        bench.workspace.move_sources_to_collection(matter.matter_id, [docs[1].document_id], second.collection_id, ACTOR)
        group = bench.workspace.create_source_set(matter.matter_id, 'Synthetic cross-collection set', [d.document_id for d in docs[:2]], ACTOR)
        scope = {'source_set': group.source_set_id}
        if restrict_collection:
            scope['collection'] = first.collection_id
        page = client.get(f'/matters/{slug}/sources/{store.action_token(docs[0])}', params={'browse': urlencode(scope)})
        search = html.unescape(re.search(r'href="([^"]+)">Search document contents</a>', page.text)[1])
        query = parse_qs(urlsplit(search).query)
        assert query['source_set'] == [group.source_set_id]
        assert query.get('collection', []) == ([first.collection_id] if restrict_collection else [])
        results = client.get(search + '&words=amber')
        assert ('1 source found' if restrict_collection else '2 sources found') in results.text
        assert 'Outside.txt' not in results.text


def test_document_passages_and_unauthorized_viewer(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        uploaded = client.post(f'/matters/{slug}/uploads',
            files=[('files', ('Synthetic.pdf', (
                Path(__file__).parents[1] / 'src/case_intelligence/demo_data/synthetic_case_report.pdf'
            ).read_bytes(), 'application/pdf'))],
            follow_redirects=False)
        assert uploaded.status_code == 303
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        document = next(iter(bench.source_store(matter).documents.values()))
        token = bench.source_store(matter).action_token(document)
        context = urlencode({'kind': 'PDF', 'sort': 'name'})
        page = client.get(f'/matters/{slug}/sources/{token}', params={'browse': context})
        next_passage = next(url for url in links(page.text) if 'unit=2' in url)
        assert parse_qs(parse_qs(urlsplit(next_passage).query)['browse'][0])['kind'] == ['PDF']
        second = client.get(next_passage)
        assert 'Page 2 of 3' in second.text and 'aria-current="page"' in sidebar(second.text)
        other = 'generated-browsing-foreign-owner'
        bench.workspace.upsert_principal('test', other, 'Synthetic foreign owner', other, preferred_principal_id=other)
        foreign = bench.create_matter('Synthetic inaccessible browsing', '', other)
        assert client.get(f'/matters/{foreign.slug}/sources/{token}', params={'browse': context}).status_code == 404


def test_direct_link_state_change_retains_unreviewed_queue(tmp_path):
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        slug = _matter(client)
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        docs = [store.store_stream(name, 'text/plain', io.BytesIO(('Synthetic queue ' + name).encode()))[0]
                for name in ('First.txt', 'Already reviewed.txt', 'Next.txt')]
        bench._sync_source_catalog(matter, list(store.documents.values()))
        bench.workspace.reconcile_source_organizations(matter.matter_id, tuple((d.document_id, 'upload', d.display_name) for d in docs))
        bench.workspace.update_source_review_state(matter.matter_id, [docs[1].document_id], 'reviewed', ACTOR)
        opened = client.get(f'/matters/{slug}/sources/{store.action_token(docs[0])}')
        action = html.unescape(re.search(r'action="([^"]+/review-state[^"]*)"', opened.text)[1])
        changed = client.post(action, data={'state': 'flagged'}, follow_redirects=False)
        assert not parse_qs(urlsplit(changed.headers['location']).query).get('browse')
        page = client.get(changed.headers['location'])
        action = html.unescape(re.search(r'action="([^"]+/review-next[^"]*)"', page.text)[1])
        continued = client.post(action, follow_redirects=False)
        assert store.action_token(docs[2]) in continued.headers['location']
