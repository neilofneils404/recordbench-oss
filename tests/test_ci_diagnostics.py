"""Exercise the hosted command, including a process that cannot finish its report."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]


def application_command(tmp_path):
    workflow = (ROOT / '.github/workflows/quality-gates.yml').read_text()
    step = workflow.split('      - name: Run application suite\n', 1)[1]
    command = re.search(r'        run: >-\n((?:          .+\n)+)', step)[1]
    command = command.replace('${{ runner.temp }}', str(tmp_path))
    argv = shlex.split(command)
    argv[0] = sys.executable
    return argv


def run_synthetic(tmp_path, source):
    (tmp_path / 'test_synthetic.py').write_text(source)
    env = dict(os.environ)
    # Do not inherit a caller's selection, tracing or plugin configuration.
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    return subprocess.run(application_command(tmp_path), cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30)


def test_completed_report_preserves_failure_skip_and_following_test(tmp_path):
    result = run_synthetic(tmp_path, '''import pytest

def test_failure():
    print("SYNTHETIC_CAPTURE_MARKER")
    assert 1 == 2

def test_skip():
    pytest.skip("synthetic prerequisite absent")

def test_after_failure():
    pass
''')
    assert result.returncode == 1
    assert 'test_failure FAILED' in result.stdout
    assert 'test_after_failure PASSED' in result.stdout
    assert 'synthetic prerequisite absent' in result.stdout
    assert 'slowest 25 durations' in result.stdout
    assert 'SYNTHETIC_CAPTURE_MARKER' not in result.stdout
    report = (tmp_path / 'application-results.xml').read_text()
    suite = ET.fromstring(report).find('testsuite')
    assert suite.attrib['tests'] == '3'
    assert suite.attrib['failures'] == '1'
    assert suite.attrib['skipped'] == '1'
    assert 'SYNTHETIC_CAPTURE_MARKER' not in report
    assert suite.findall('.//system-out') == []
    assert suite.findall('.//system-err') == []


@pytest.mark.parametrize('phase', ['setup', 'call', 'teardown'])
def test_failed_node_survives_abrupt_exit_without_session_summary(tmp_path, phase):
    fixture = '''import os
import pytest

@pytest.fixture
def synthetic_fixture():
    SETUP
    yield
    TEARDOWN

def test_failure(synthetic_fixture):
    CALL

def test_abrupt_exit():
    os._exit(7)
'''.replace('SETUP', 'assert False' if phase == 'setup' else 'pass').replace(
        'TEARDOWN', 'assert False' if phase == 'teardown' else 'pass').replace(
        'CALL', 'assert False' if phase == 'call' else 'pass')
    result = run_synthetic(tmp_path, fixture)
    assert result.returncode == 7
    outcome = 'FAILED' if phase == 'call' else 'ERROR'
    assert f'test_synthetic.py::test_failure {outcome}' in result.stdout
    assert 'test_synthetic.py::test_abrupt_exit' in result.stdout
    assert not (tmp_path / 'application-results.xml').exists()
