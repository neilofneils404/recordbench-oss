"""Synthetic search-to-source-to-question navigation with matter-local returns."""
import html
import io
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from case_intelligence.workbench import create_workbench_app


@pytest.mark.parametrize('origin', ['search', 'https://example.com/', '/matters/another/exact-search', '/matters/{slug}/../another'])
def test_search_inspection_and_question_return_is_matter_local(tmp_path, origin):
    app = create_workbench_app(tmp_path / 'runtime', auth_mode='test', background_ingestion=False)
    with TestClient(app) as client:
        created = client.post('/matters', data={'name': 'Synthetic navigation'}, follow_redirects=False)
        slug = created.headers['location'].split('/')[2]
        bench = app.state.workbench
        matter = bench.matter(slug, 'development-taylor-morgan')
        bench.source_store(matter).store_stream('Synthetic neutral.txt', 'text/plain', io.BytesIO(b'An amber bicycle arrived.'))
        search = f'/matters/{slug}/exact-search?words=amber&page_size=25'
        results = client.get(search)
        assert '1 source found' in results.text
        link = html.unescape(re.search(r'class="find-open-source" href="([^"]+)"', results.text)[1])
        assert parse_qs(urlsplit(link).query)['entity_return_to'] == [search]
        source = client.get(link)
        assert html.escape(search, quote=True) in source.text
        action = html.unescape(re.search(r'<form method="post" action="([^"]+/ask[^\"]*)"', source.text)[1])
        path = urlsplit(action).path
        response = client.post(path, params={'entity_return_to': search if origin == 'search' else origin.format(slug=slug)}, follow_redirects=False)
        query = parse_qs(urlsplit(response.headers['location']).query)
        assert 'source_set' in query
        assert query.get('entity_return_to', []) == ([search] if origin == 'search' else [])
        conversation = client.get(response.headers['location'])
        assert 'Case conversation' in conversation.text
        assert 'Only · Synthetic neutral.txt' in conversation.text
