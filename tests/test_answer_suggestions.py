"""Synthetic regression: suggest people, things and dates from an answer's cited passages."""
import copy
import io
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from case_intelligence.entity_repository import ANSWER_HISTORY_ACTION
from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app

ACTOR = 'development-taylor-morgan'
OWNER = 'synthetic-suggest-owner'
TEXT = b'witness: Alex Example\nThe crate was signed for on 2026-03-05.\nbadge: AB-1234\n'


def seed(bench, text=TEXT):
    bench.workspace.upsert_principal('test', OWNER, 'Synthetic Owner', OWNER, preferred_principal_id=OWNER)
    matter = bench.create_matter('Synthetic answer suggestions', 'Generated evidence', OWNER)
    bench.workspace.add_member(matter.matter_id, ACTOR, OWNER)
    store = bench.source_store(matter)
    document = store.store_stream('Synthetic receiving log.txt', 'text/plain', io.BytesIO(text))[0]
    bench._sync_source_catalog(matter, (document,))
    citation = bench._citation(matter, bench._candidate(matter, document, document.parsed_units()[0], 1))
    conversation = bench.workspace.get_conversation(matter.matter_id)
    message = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        'assistant', 'Synthetic answer', {'kind': 'generated', 'claims': [
            {'text': 'Alex Example signed for the crate.', 'citations': [bench._saved_answer_citation_payload(citation)]}]})
    url = (f'/matters/{matter.slug}/conversations/{conversation.conversation_id}'
           f'/messages/{message.message_id}/suggestions/claims/0')
    return matter, conversation, message, url


@pytest.fixture
def answer(tmp_path, monkeypatch):
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    monkeypatch.delenv('CASE_INTELLIGENCE_AUTOMATIC_DISCOVERY', raising=False)
    with TestClient(create_workbench_app(tmp_path / 'runtime',
            generator=UnavailableGenerator(), auth_mode='test')) as client:
        client.get('/')  # establish the synthetic development principal
        yield client, seed(client.app.state.workbench)


def identities(bench, matter):
    service = bench.entity_service(matter)
    rows, _total = service.list(matter.matter_id, ACTOR)
    return {row['display_name']: row for row in rows}


def test_cited_passages_become_suggestions_that_record_they_came_from_an_answer(answer):
    client, (matter, conversation, message, url) = answer
    bench = client.app.state.workbench
    first = client.post(url, headers={'Accept': 'application/json'})
    assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
    body = first.json()
    assert body['added'] == 3 and body['dates'] == 1
    assert body['message'] == 'Added 3 suggestions for review, including 1 date.'
    assert body['inbox_url'] == f'/matters/{matter.slug}/entities#suggestions'
    assert body['timeline_url'] == f'/matters/{matter.slug}/chronology#found-dates-heading'
    rows = identities(bench, matter)
    assert set(rows) == {'Alex Example', '2026-03-05', 'AB-1234'}
    assert {row['status'] for row in rows.values()} == {'suggested'}
    # Created by the reviewer, with the answer recorded as the first history entry.
    with bench.workspace._lock:
        history = bench.workspace.connection.execute(
            'SELECT h.action, e.created_by FROM workbench_entity_history h JOIN workbench_entity e '
            'ON e.entity_id=h.entity_id WHERE e.matter_id=? AND h.revision=1', (matter.matter_id,)).fetchall()
    assert {(row[0], row[1]) for row in history} == {(ANSWER_HISTORY_ACTION, ACTOR)}
    # The inbox shows the provenance; a repeat adds nothing.
    inbox = client.get(f'/matters/{matter.slug}/entities').text
    assert inbox.count('suggestion-from-answer">From an answer</span>') == 3
    again = client.post(url, headers={'Accept': 'application/json'}).json()
    assert again['added'] == 0 and again['timeline_url'] == ''
    assert again['message'] == 'No new people, things or dates: they are already suggested, or none were found.'
    assert len(identities(bench, matter)) == 3


def test_answer_suggestions_and_discovery_never_duplicate_an_occurrence(answer):
    client, (matter, conversation, message, url) = answer
    bench = client.app.state.workbench
    assert client.post(url, headers={'Accept': 'application/json'}).json()['added'] == 3
    bench.run_automatic_discovery_once()
    assert len(identities(bench, matter)) == 3
    # The other way round: what discovery already found is not suggested again from an answer.
    other = seed(bench, b'witness: Morgan Ellis\nA second synthetic log dated 2026-04-01.\n')
    bench.run_automatic_discovery_once()
    response = client.post(other[3], headers={'Accept': 'application/json'}).json()
    assert response['added'] == 0
    inbox = client.get(f'/matters/{other[0].slug}/entities').text
    assert 'From an answer' not in inbox


def test_a_changed_citation_lost_access_and_missing_claims_suggest_nothing(answer):
    client, (matter, conversation, message, url) = answer
    bench = client.app.state.workbench
    payload = copy.deepcopy(message.payload)
    payload['claims'][0]['citations'][0]['excerpt_digest'] = 'f' * 64
    stale = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        'assistant', 'Synthetic stale answer', payload)
    stale_url = url.replace(message.message_id, stale.message_id)
    response = client.post(stale_url, headers={'Accept': 'application/json'})
    assert response.status_code == 409 and 'changed or are unavailable' in response.json()['message']
    legacy = client.post(stale_url, follow_redirects=False)
    assert legacy.status_code == 303 and 'error' in parse_qs(urlsplit(legacy.headers['location']).query)
    assert client.post(url[:-1] + '9', headers={'Accept': 'application/json'}).status_code == 404
    other = bench.create_matter('Other synthetic matter', 'Generated isolation', ACTOR)
    assert client.post(url.replace(matter.slug, other.slug), headers={'Accept': 'application/json'}).status_code == 404
    assert not identities(bench, matter)
    bench.workspace.revoke_member(matter.matter_id, ACTOR, OWNER)
    assert client.post(url, headers={'Accept': 'application/json'}).status_code in (403, 404)


def test_without_javascript_the_reviewer_returns_to_the_same_place_with_a_notice(answer):
    client, (matter, conversation, message, url) = answer
    reader = f'/matters/{matter.slug}/sources?query=crate#source-section-1'
    response = client.post(url, data={'return_to': reader}, follow_redirects=False)
    assert response.status_code == 303
    parsed = urlsplit(response.headers['location'])
    assert parsed.path == f'/matters/{matter.slug}/sources' and parsed.fragment == 'source-section-1'
    assert parse_qs(parsed.query)['notice'] == ['Added 3 suggestions for review, including 1 date.']
    outside = client.post(url, data={'return_to': 'https://example.invalid/'}, follow_redirects=False)
    assert urlsplit(outside.headers['location']).path == f'/matters/{matter.slug}'


def test_suggesting_requires_the_session_csrf_token(tmp_path, monkeypatch):
    from tests.test_identity_membership_audit import _login
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    with TestClient(create_workbench_app(tmp_path / 'runtime',
            generator=UnavailableGenerator(), auth_mode='preview')) as client:
        _, csrf = _login(client, 'taylor-morgan')
        bench = client.app.state.workbench
        matter, conversation, message, url = seed(bench)
        assert client.post(url, headers={'Accept': 'application/json'}).status_code == 403
        assert client.post(url, data={'csrf_token': 'invalid'}, headers={'Accept': 'application/json'}).status_code == 403
        assert not identities(bench, matter)
        assert client.post(url, data={'csrf_token': csrf}, headers={'Accept': 'application/json'}).json()['added'] == 3


def test_the_action_appears_on_each_claim_in_the_dock_and_the_full_conversation(answer):
    client, (matter, conversation, message, url) = answer
    dock = client.get(f'/matters/{matter.slug}/assistant', params={'conversation': conversation.conversation_id}).text
    form = re.search(r'<form class="save-claim-form" method="post" action="' + re.escape(url) + r'" data-assistant-suggest-passage>(.*?)</form>', dock, re.S)
    assert form and 'Suggest people, things and dates from this passage' in form[1]
    assert 'data-suggest-passage-status role="status"' in form[1]
    assert re.search(r'data-suggest-inbox hidden>Review suggestions</a>', form[1])
    assert re.search(r'data-suggest-timeline hidden>See dates in the timeline draft</a>', form[1])
    full = client.get(f'/matters/{matter.slug}', params={'conversation': conversation.conversation_id}).text
    assert f'action="{url}"' in full


def test_a_current_passage_is_still_used_when_another_citation_changed(answer):
    client, (matter, conversation, message, url) = answer
    bench = client.app.state.workbench
    payload = copy.deepcopy(message.payload)
    stale = copy.deepcopy(payload['claims'][0]['citations'][0])
    stale['excerpt_digest'] = 'f' * 64
    payload['claims'][0]['citations'].insert(0, stale)
    mixed = bench.workspace.append_message(matter.matter_id, conversation.conversation_id,
        'assistant', 'Synthetic mixed answer', payload)
    body = client.post(url.replace(message.message_id, mixed.message_id), headers={'Accept': 'application/json'}).json()
    assert body['added'] == 3
    assert body['message'] == ('Added 3 suggestions for review, including 1 date. '
                               'Cited passages that changed were skipped.')
