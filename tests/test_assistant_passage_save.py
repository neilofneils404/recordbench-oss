"""Synthetic dock saves reuse the existing notebook boundary."""
import io
import copy
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app

ACTOR = 'development-taylor-morgan'


def seed(bench):
    owner = 'synthetic-dock-owner'
    bench.workspace.upsert_principal('test', owner, 'Synthetic Owner', owner,
                                    preferred_principal_id=owner)
    matter = bench.create_matter('Synthetic dock save', 'Generated evidence', owner)
    bench.workspace.add_member(matter.matter_id, ACTOR, owner)
    store = bench.source_store(matter)
    document = store.store_stream('Generated observation.txt', 'text/plain',
        io.BytesIO(b'The synthetic blue gauge showed twelve units.\n' * 80))[0]
    bench._sync_source_catalog(matter, (document,))
    citation = bench._citation(matter, bench._candidate(matter, document, document.parsed_units()[0], 1))
    conversation = bench.workspace.get_conversation(matter.matter_id)
    message = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        'assistant', 'Synthetic observation', {'kind': 'generated', 'claims': [
            {'text': 'The synthetic gauge showed twelve units.', 'citations': [bench._saved_answer_citation_payload(citation)]}]})
    url = (f'/matters/{matter.slug}/conversations/{conversation.conversation_id}'
           f'/messages/{message.message_id}/notebook/claims/0')
    return matter, conversation, message, document, url


@pytest.fixture
def saved_answer(tmp_path, monkeypatch):
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    with TestClient(create_workbench_app(tmp_path / 'runtime',
            generator=UnavailableGenerator(), auth_mode='test')) as client:
        client.get('/')  # establish the synthetic development principal
        yield client, seed(client.app.state.workbench)


def test_dock_save_and_full_conversation_compatibility(saved_answer):
    client, (matter, conversation, message, document, url) = saved_answer
    dock = client.get(f'/matters/{matter.slug}/assistant',
                      params={'conversation': conversation.conversation_id})
    assert 'data-assistant-save-passage' in dock.text
    assert url in dock.text
    assert 'role="status" aria-live="polite" aria-atomic="true"' in dock.text
    first = client.post(url, headers={'Accept': 'application/json'})
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-store'
    assert first.json()['created'] is True
    assert first.json()['status'] == 'suggested'
    again = client.post(url, headers={'Accept': 'application/json'})
    assert again.json()['created'] is False
    assert again.json()['item_id'] == first.json()['item_id']
    store = client.app.state.workbench.workspace
    item = store.notebook_item(matter.matter_id, ACTOR, first.json()['item_id'])
    store.set_notebook_item_status(matter.matter_id, ACTOR, item.item_id, 'confirmed',
                                  expected_updated_at=item.updated_at)
    reviewed_repeat = client.post(url, headers={'Accept': 'application/json'})
    assert reviewed_repeat.json()['status'] == 'confirmed'
    assert reviewed_repeat.json()['created'] is False
    legacy = client.post(url, follow_redirects=False)
    assert legacy.status_code == 303
    assert parse_qs(urlsplit(legacy.headers['location']).query)['conversation'] == [conversation.conversation_id]
    assert legacy.headers['location'].endswith('#latest')
    assert len(client.app.state.workbench.workspace.all_notebook_items(matter.matter_id, ACTOR)) == 1


@pytest.mark.parametrize('destination', [None, 'https://example.invalid/', '//example.invalid',
    '/matters/other/sources', '/matters/SLUG/../other', '/matters/SLUG/%252e%252e/other'])
def test_non_js_return_is_same_matter(saved_answer, destination):
    client, (matter, conversation, message, document, url) = saved_answer
    expected = f'/matters/{matter.slug}/sources?query=gauge&status=ready&conversation={conversation.conversation_id}#source-section-1'
    target = expected if destination is None else destination.replace('SLUG', matter.slug)
    response = client.post(url, data={'return_to': target}, follow_redirects=False)
    assert response.status_code == 303
    parsed = urlsplit(response.headers['location'])
    assert not parsed.netloc
    assert parsed.path == (f'/matters/{matter.slug}/sources' if destination is None else f'/matters/{matter.slug}')
    if destination is None:
        assert parsed.fragment == 'source-section-1'
        assert parse_qs(parsed.query)['query'] == ['gauge']
        assert parse_qs(parsed.query)['status'] == ['ready']


def test_stale_citation_and_lost_access_do_not_save(saved_answer):
    client, (matter, conversation, message, document, url) = saved_answer
    bench = client.app.state.workbench
    payload = copy.deepcopy(message.payload)
    payload['claims'][0]['citations'][0]['excerpt_digest'] = 'f' * 64
    stale_message = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        'assistant', 'Synthetic stale answer', payload)
    url = url.replace(message.message_id, stale_message.message_id)
    stale = client.post(url, headers={'Accept': 'application/json'})
    assert stale.status_code == 409
    assert 'message' in stale.json()
    assert not bench.workspace.all_notebook_items(matter.matter_id, ACTOR)
    bench.workspace.revoke_member(matter.matter_id, ACTOR, 'synthetic-dock-owner')
    denied = client.post(url, headers={'Accept': 'application/json'})
    assert denied.status_code in (403, 404)
    assert not bench.workspace.all_notebook_items(matter.matter_id, 'synthetic-dock-owner')


def test_dock_save_requires_session_csrf(tmp_path, monkeypatch):
    from tests.test_identity_membership_audit import _login
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    with TestClient(create_workbench_app(tmp_path / 'runtime',
            generator=UnavailableGenerator(), auth_mode='preview')) as client:
        _, csrf = _login(client, 'taylor-morgan')
        matter, conversation, message, document, url = seed(client.app.state.workbench)
        assert client.post(url, headers={'Accept': 'application/json'}).status_code == 403
        assert client.post(url, data={'csrf_token': 'invalid'},
                           headers={'Accept': 'application/json'}).status_code == 403
        assert not client.app.state.workbench.workspace.all_notebook_items(matter.matter_id, ACTOR)
        assert client.post(url, data={'csrf_token': csrf},
                           headers={'Accept': 'application/json'}).json()['created'] is True


def test_missing_and_cross_matter_claims_cannot_save(saved_answer):
    client, (matter, conversation, message, document, url) = saved_answer
    assert client.post(url[:-1] + '99', headers={'Accept': 'application/json'}).status_code == 404
    bench = client.app.state.workbench
    other = bench.create_matter('Other synthetic dock matter', 'Generated isolation', ACTOR)
    assert client.post(url.replace(matter.slug, other.slug),
                       headers={'Accept': 'application/json'}).status_code == 404
    assert not bench.workspace.all_notebook_items(matter.matter_id, ACTOR)
    assert not bench.workspace.all_notebook_items(other.matter_id, ACTOR)
