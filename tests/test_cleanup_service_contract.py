"""No HTTP probe for non-HTTP cleanup; actual shell loop fails on cleanup error."""
import ast
import re
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]

def service_section(name):
    content = (ROOT / 'compose.yaml').read_text().split('\n  ' + name + ':\n', 1)[1]
    return re.split(r'\n  [a-z][a-z-]*:\n', content, maxsplit=1)[0]


def test_cleanup_roles_do_not_inherit_api_http_probe():
    for role in ['transcription-cleanup', 'transcription-cleanup-daemon']:
        section = service_section(role)
        assert re.search(r'healthcheck:\n +disable: true', section)
        assert 'network_mode: none' in section
    assert 'disable: true' not in service_section('transcription-api')
    image = (ROOT / 'services/transcription/Dockerfile').read_text()
    assert 'http://127.0.0.1:8510/health' in image


@pytest.mark.parametrize('cleanup_status', [0, 23])
def test_cleanup_loop_stops_on_failure_and_sleeps_only_after_success(tmp_path, cleanup_status):
    section = service_section('transcription-cleanup-daemon')
    entrypoint = ast.literal_eval(re.search(r'entrypoint: (.+)', section)[1])
    command = re.search(r'command:\n + - (.+)', section)[1]
    for name, body in {
        'transcription-v2': '#!/bin/sh\nprintf "cleanup:%s\\n" "$1" >> "$CLEANUP_TEST_TRACE"\nexit "$CLEANUP_TEST_STATUS"\n',
        'sleep': '#!/bin/sh\nprintf "sleep:%s\\n" "$1" >> "$CLEANUP_TEST_TRACE"\nexit 75\n',
    }.items():
        target = tmp_path / name
        target.write_text(body)
        target.chmod(0o700)
    trace = tmp_path / 'trace'
    environment = dict(os.environ, PATH=str(tmp_path), CLEANUP_TEST_TRACE=str(trace),
                       CLEANUP_TEST_STATUS=str(cleanup_status))
    run = subprocess.run(entrypoint + [command], env=environment,
                         capture_output=True, timeout=5)
    assert run.returncode == (cleanup_status or 75)
    assert trace.read_text().splitlines() == (
        ['cleanup:purge-expired'] if cleanup_status else ['cleanup:purge-expired', 'sleep:300'])
