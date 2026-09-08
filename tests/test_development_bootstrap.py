from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'scripts' / 'bootstrap-dev.py'


@pytest.fixture
def bootstrap():
    spec = importlib.util.spec_from_file_location('development_bootstrap', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_does_not_create_environment_or_claim_readiness(tmp_path):
    environment = tmp_path / 'dev environment'
    result = subprocess.run([sys.executable, str(SCRIPT), '--venv', str(environment),
                             '--dry-run'], check=True, capture_output=True, text=True)
    assert not environment.exists()
    assert '.[dev,postgres]' in result.stdout
    assert './services/transcription[dev]' in result.stdout
    assert 'Preview only' in result.stdout
    assert 'environment ready' not in result.stdout
    assert 'Next: make check' not in result.stdout


@pytest.mark.parametrize('version', [(3, 11), (3, 13), (3, 14)])
def test_unsupported_target_rejected_before_mutation(bootstrap, tmp_path, monkeypatch, version):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'version': version, 'base_executable': '/synthetic/python', 'is_venv': False}))
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    with pytest.raises(ValueError, match='Python 3.12'):
        bootstrap.bootstrap(venv=tmp_path / 'env', python='chosen-python', dry_run=False)
    assert len(calls) == 1
    assert calls[0][0] == 'chosen-python'
    assert not (tmp_path / 'env').exists()


def test_selected_interpreter_is_checked_instead_of_launcher(bootstrap, tmp_path, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'version': [3, 12], 'base_executable': '/synthetic/python', 'is_venv': False}))
    monkeypatch.setattr(bootstrap.sys, 'version_info', (3, 11))
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    bootstrap.bootstrap(venv=tmp_path / 'env', python='chosen-python', dry_run=True)
    assert len(calls) == 1
    assert calls[0][0] == 'chosen-python'


def test_existing_non_environment_is_preserved(bootstrap, tmp_path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('keep')
    with pytest.raises(ValueError, match='virtual environment'):
        bootstrap.bootstrap(venv=tmp_path, python=sys.executable, dry_run=False)
    assert marker.read_text() == 'keep'
    assert not (tmp_path / 'pyvenv.cfg').exists()


@pytest.mark.parametrize('version,base,is_venv', [([3, 13], '/synthetic/python', True),
                                               ([3, 12], '/different/python', True),
                                               ([3, 12], '/synthetic/python', False)])
def test_incompatible_environment_is_preserved(bootstrap, tmp_path, monkeypatch, version, base, is_venv):
    (tmp_path / 'pyvenv.cfg').write_text('original config')
    env_python = bootstrap.environment_interpreter(tmp_path)
    env_python.parent.mkdir()
    env_python.write_text('original interpreter')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        info = {'version': [3, 12], 'base_executable': '/synthetic/python', 'is_venv': False}
        if len(calls) == 2:
            info = {'version': version, 'base_executable': base, 'is_venv': is_venv}
        return subprocess.CompletedProcess(command, 0, json.dumps(info))
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    with pytest.raises(ValueError, match='different|incompatible'):
        bootstrap.bootstrap(venv=tmp_path, python='chosen-python', dry_run=False)
    assert len(calls) == 2
    assert (tmp_path / 'pyvenv.cfg').read_text() == 'original config'
    assert env_python.read_text() == 'original interpreter'


def test_install_failure_has_recovery_and_no_readiness(bootstrap, tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        raise subprocess.CalledProcessError(1, ['pip'])
    monkeypatch.setattr(bootstrap, 'bootstrap', fail)
    assert bootstrap.main(['--venv', str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert 'ready' not in output.out
    assert 'rerun' in output.err.lower()


def test_bare_make_still_runs_tests():
    result = subprocess.run(['make', '-n'], cwd=ROOT, check=True, capture_output=True, text=True)
    assert '-m pytest' in result.stdout
    assert 'bootstrap-dev' not in result.stdout


def test_make_transcription_accepts_external_path_with_spaces(tmp_path):
    shutil.copyfile(ROOT / 'Makefile', tmp_path / 'Makefile')
    service = tmp_path / 'services' / 'transcription'
    (service / 'tests').mkdir(parents=True)
    (service / 'src').mkdir()
    (service / 'src' / 'synthetic_module.py').write_text('VALUE = 42\n')
    (service / 'tests' / 'test_synthetic.py').write_text(
        'from pathlib import Path\nimport synthetic_module\n'
        'def test_service_context():\n'
        '    assert Path.cwd().name == "transcription"\n'
        '    assert synthetic_module.VALUE == 42\n')
    interpreter = tmp_path / 'external environment' / 'python'
    interpreter.parent.mkdir()
    interpreter.write_text('#!/bin/sh\nexec "' + sys.executable + '" "$@"\n')
    interpreter.chmod(0o700)
    result = subprocess.run(['make', 'test-transcription', f'PYTHON={interpreter}'], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout
