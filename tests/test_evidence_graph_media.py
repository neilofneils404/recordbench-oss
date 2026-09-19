"""Graph traversal retains independently cited written and recorded originals."""
from urllib.parse import urlencode
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from case_intelligence.generation import UnavailableGenerator
from case_intelligence.workbench import create_workbench_app
from tests.test_matter_media_workflow import ACTOR, PDF, WAV, ImmediateMediaProcessor, _matter


@pytest.mark.parametrize('written_kind', ('text', 'pdf'))
def test_graph_opens_written_original_and_cited_audio_moment_without_generator(tmp_path, monkeypatch, written_kind):
    if written_kind == 'pdf' and sys.platform != 'linux':
        pytest.skip('The production PDF child-process resource limits require Linux; native text/audio path is tested separately.')
    monkeypatch.setenv('CASE_INTELLIGENCE_STORAGE_RESERVE_GIB', '0')
    # The supported Linux profile uses these fixed tool paths. Exercise the real
    # decoders from PATH on other contributor hosts without changing app defaults.
    def portable_command(command):
        if isinstance(command, (list, tuple)) and command and command[0] in ('/usr/bin/ffprobe', '/usr/bin/ffmpeg'):
            if not Path(command[0]).exists():
                binary = shutil.which(Path(command[0]).name)
                assert binary, 'Media graph acceptance requires ffprobe and ffmpeg.'
                command = [binary, *command[1:]]
        return command
    from case_intelligence import media_preflight, pilot_uploads
    shim = SimpleNamespace(**{**vars(subprocess),
        'run': lambda command, *args, **kwargs: subprocess.run(portable_command(command), *args, **kwargs),
        'Popen': lambda command, *args, **kwargs: subprocess.Popen(portable_command(command), *args, **kwargs)})
    monkeypatch.setattr(pilot_uploads, 'subprocess', shim)
    monkeypatch.setattr(media_preflight, 'subprocess', shim)
    app = create_workbench_app(tmp_path / 'runtime', generator=UnavailableGenerator(),
        auth_mode='test', media_processor=ImmediateMediaProcessor(), media_poll_seconds=0.01)
    with TestClient(app) as client:
        slug = _matter(client, 'Synthetic written and recorded graph')
        uploaded_audio = client.post(f'/matters/{slug}/uploads', files=[('files', (
            'Generated recording.wav', WAV.read_bytes(), 'audio/wav'))], follow_redirects=False)
        assert uploaded_audio.status_code == 303
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        store = bench.source_store(matter)
        recording = next(iter(store.documents.values()))
        deadline, continued = time.monotonic() + 10, False
        while time.monotonic() < deadline:
            job = bench.workspace.media_job(matter.matter_id, recording.document_id, recording.version_id)
            if recording.state == 'ready' and job and job.state in ('succeeded', 'degraded'):
                break
            if recording.state == 'needs_review' and job and job.state == 'cancelled' and not continued:
                # Explicitly admit the controlled transcript through the normal
                # recording-check action. This test does not evaluate ASR.
                response = client.post(f'/matters/{slug}/sources/{store.action_token(recording)}/recording-check',
                    data={'action': 'continue', 'inspection_id': job.preflight['inspection_id']}, follow_redirects=False)
                assert response.status_code == 303
                continued = True
            time.sleep(0.01)
        assert recording.state == 'ready' and job and job.state in ('succeeded', 'degraded')
        written_type = 'application/pdf' if written_kind == 'pdf' else 'text/plain'
        written_bytes = PDF.read_bytes() if written_kind == 'pdf' else b'The red bicycle was logged at the north entrance.'
        uploaded = client.post(f'/matters/{slug}/uploads', files=[('files', (
            'Generated incident report.' + ('pdf' if written_kind == 'pdf' else 'txt'),
            written_bytes, written_type))], follow_redirects=False)
        assert uploaded.status_code == 303
        bench = app.state.workbench
        matter = bench.matter(slug, ACTOR)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            document = next((row for row in store.documents.values() if row.media_type == written_type), None)
            if document and document.state in ('ready', 'failed', 'needs_ocr'):
                break
            time.sleep(0.01)
        assert document and document.state == 'ready', document.message if document else 'Written source was not admitted'
        ordinal = 2 if written_kind == 'pdf' else 1
        written = bench._support_token(bench._candidate(matter, document, document.parsed_units()[ordinal - 1], ordinal))
        spoken = bench._support_token(bench._candidate(matter, recording, recording.parsed_units()[0], 1))
        entities, assertions = bench.entity_service(matter), bench.assertion_service(matter)
        entity = entities.create(matter.matter_id, ACTOR, display_name='Synthetic red bicycle', entity_type='thing')
        record = assertions.create(matter.matter_id, ACTOR, title='Written and spoken location accounts',
            statement='Compare the accounts of where the bicycle was logged.', record_type='event',
            support=written, attributed_to='Generated written report', roles=[dict(
                entity_id=entity['entity_id'], expected_revision=entity['revision'], role='object')])
        assertions.attach(matter.matter_id, ACTOR, record['assertion_id'], expected_revision=record['revision'],
            support=spoken, stance='supporting', attributed_to='Synthetic recording transcript')
        graph_path = f'/matters/{slug}/connections?' + urlencode(dict(entity_id=entity['entity_id']))
        graph = client.get(graph_path)
        assert graph.status_code == 200
        assert 'Generated written report' in graph.text and 'Synthetic recording transcript' in graph.text
        for token, kind in ((written, 'document'), (spoken, 'transcript')):
            assert token in graph.text
            support = bench.support(matter, token)
            assert support.evidence_kind == kind
            opened = client.get(f'/matters/{slug}', params=dict(support=token, entity_return_to=graph_path))
            assert opened.status_code == 200 and 'Return to review context' in opened.text
            if kind == 'document':
                if written_kind == 'pdf':
                    assert support.location == 'Page 2'
                    assert 'Page 2 of 3' in opened.text and 'Open full PDF' in opened.text
                else:
                    assert 'red bicycle was logged at the north entrance' in opened.text
            else:
                assert (support.start_ms, support.end_ms) == (0, 2000)
                assert 'data-support-media data-start-ms="0"' in opened.text
                assert 'Play cited moment' in opened.text
