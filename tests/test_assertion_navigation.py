"""Unsafe return destinations must not interrupt or escape a matter review."""
import html
import re

from fastapi.testclient import TestClient
import pytest

from tests.test_assertion_workflow import _app, _create_event, _entity, _passage, _upload
from tests.test_matter_notebook import _create_matter


@pytest.mark.parametrize('destination', [
    'https://[',
    'https://outside.example.test／review',
    '{prefix}/../other-synthetic-scope/chronology',
    '{prefix}/%2e%2e/other-synthetic-scope/chronology',
    '{prefix}/.%2E/other-synthetic-scope/chronology',
    '{prefix}/%252e%252e/other-synthetic-scope/chronology',
    '{prefix}/%2e%2e%2fother-synthetic-scope/chronology',
    '{prefix}/%5c..%5cother-synthetic-scope/chronology',
])
def test_unsafe_return_url_keeps_entity_assertion_and_original_views_usable(
    tmp_path, monkeypatch, destination,
):
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    with TestClient(_app(tmp_path / 'runtime')) as client:
        slug = _create_matter(client)
        prefix = f'/matters/{slug}'
        destination = destination.format(prefix=prefix)
        _upload(client, slug)
        token, _, _ = _passage(client, slug, 'Morgan')
        entity_id = _entity(client, slug, 'Alex Example', support=token)
        assertion_id = _create_event(client, slug, entity_id, token)
        for path in (prefix + '/entities/' + entity_id,
                     prefix + '/assertions/' + assertion_id):
            page = client.get(path, params=dict(return_to=destination))
            assert page.status_code == 200
            returned = re.search(r'href="([^"]+)">Return to source review</a>', page.text)
            assert returned and html.unescape(returned.group(1)) == prefix
        # Both original readers receive the same untrusted context parameter.
        # A malformed destination must hide the return action, not fail a read.
        pane = client.get(prefix, params=dict(support=token, entity_return_to=destination))
        assert pane.status_code == 200 and 'Return to review context' not in pane.text
        full_link = re.search(r'class="support-header-open" href="([^"]+)"', pane.text)
        assert full_link
        full = client.get(html.unescape(full_link.group(1)))
        assert full.status_code == 200 and 'Return to review context' not in full.text
        assert 'Morgan Sample says Alex Example delivered the red parcel' in full.text
