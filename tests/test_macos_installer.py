"""Synthetic Mac node contracts; no host runtime or secrets required."""
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'scripts'))
spec = importlib.util.spec_from_file_location('mac_installer', PROJECT / 'scripts/mac-install.py')
mac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac)
stage_spec = importlib.util.spec_from_file_location('model_stager', PROJECT / 'scripts/stage-models.py')
stager = importlib.util.module_from_spec(stage_spec)
stage_spec.loader.exec_module(stager)


def test_root_rejects_repository_home_and_symlink(tmp_path):
    for path in (Path('/'), Path.home(), PROJECT, PROJECT / 'private-node'):
        with pytest.raises(RuntimeError):
            mac.checked_root(path)
    link = tmp_path / 'link'
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError):
        mac.checked_root(link / 'node')


def test_vm_is_native_scoped_and_preserves_global_context(tmp_path):
    command = mac.vm_command(tmp_path / 'node with spaces')
    assert '--activate=false' in command
    assert '--ssh-config=false' in command
    assert command[command.index('--arch') + 1] == 'aarch64'
    assert command[command.index('--mount') + 1] == f'{tmp_path}/node with spaces:w'
    assert '--network-address' not in command
    assert '--ssh-agent' not in command


def test_docker_commands_ignore_other_deployment_exports_without_mutating_the_shell(monkeypatch):
    overrides = {
        'RECORDBENCH_STORAGE_ROOT': '/srv/synthetic-other-node',
        'RECORDBENCH_RELEASE_ID': 'synthetic-other-release',
        'COMPOSE_PROFILES': 'transcription',
        'COMPOSE_FILE': 'synthetic-other-compose.yaml',
        'DOCKER_HOST': 'unix:///tmp/synthetic-other-daemon.sock',
        'DOCKER_CONTEXT': 'synthetic-other-context',
        'DOCKER_TLS_VERIFY': '1',
        'DOCKER_CERT_PATH': '/tmp/synthetic-certificates',
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('PATH', '/usr/bin:/bin')
    captured = []
    monkeypatch.setattr(mac.subprocess, 'run', lambda command, **kwargs: captured.append(kwargs))
    mac.run(['docker', '--context', 'colima-recordbench', 'compose', 'up', '-d'])
    child = captured[0]['env']
    assert not overrides.keys() & child.keys()
    assert child['PATH'] == '/usr/bin:/bin'
    assert all(os.environ[key] == value for key, value in overrides.items())


def test_mac_compose_rejects_linux_installation(monkeypatch, tmp_path):
    monkeypatch.setattr(mac.node, '_installed_release', lambda _: ({'platform': 'linux'}, tmp_path))
    with pytest.raises(RuntimeError, match='not a Mac'):
        mac.compose(tmp_path)


def test_retrieval_staging_omits_only_generator():
    groups = frozenset({'review', 'transcription-asr'})
    generator = {'group': 'review', 'role': 'generator', 'profile': 'portable'}
    assert stager._selected(generator, groups, review_profile='portable')
    assert not stager._selected(generator, groups, review_profile='portable', retrieval_only=True)
    for group, role in [('review', 'embedding'), ('review', 'reranker'), ('transcription-asr', 'asr')]:
        assert stager._selected({'group': group, 'role': role}, groups, review_profile='portable', retrieval_only=True)


def test_mac_config_has_small_reserves_and_explicit_capabilities(monkeypatch, tmp_path):
    root = tmp_path / 'node'
    monkeypatch.setattr(mac.node, '_stage_release', lambda *a, **kw: ('synthetic', tmp_path / 'release'))
    # Certificate generation is incidental to configuration semantics.
    def fake_run(console, command, **kwargs):
        (root / 'tls/tls.key').write_text('synthetic key placeholder')
        (root / 'tls/tls.crt').write_text('synthetic cert placeholder')
    monkeypatch.setattr(mac.node, '_run', fake_run)
    mac.configure(root, capabilities='all', port=9443)
    metadata = json.loads((root / 'installation.json').read_text())
    assert metadata['platform'] == 'macos-arm64'
    assert metadata['profiles'] == ['ai', 'transcription']
    app = mac.node._dotenv(root / 'config/recordbench.env')
    assert app['CASE_INTELLIGENCE_SECURE_COOKIE'] == '1'
    assert app['CASE_INTELLIGENCE_STORAGE_RESERVE_GIB'] == '15'
    assert app['CASE_INTELLIGENCE_GENERATOR_BACKEND'] == 'ollama'
    assert app['CASE_INTELLIGENCE_GENERATOR_MAX_OUTPUT_TOKENS'] == '1200'
    assert app['CASE_INTELLIGENCE_GENERATOR_MAX_REVIEW_TOKENS'] == '400'
    transcription = mac.node._dotenv(root / 'config/transcription.env')
    assert transcription['TRANSCRIPTION_V2_DEVICE'] == 'cpu'
    assert transcription['TRANSCRIPTION_V2_PIPELINE'] == 'whisperx'
    for file in (root / 'compose.env', root / 'installation.json', root / 'config/recordbench.env'):
        assert file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match='already configured'):
        mac.configure(root, capabilities='none', port=9443)


@pytest.mark.parametrize('failure', ['missing_worker', 'stopped_worker', 'unhealthy_service', 'wrong_artifact', None])
@pytest.mark.parametrize('listing_format', ['array', 'json_lines'])
def test_doctor_requires_the_worker_services_and_pinned_native_artifact(
    monkeypatch, tmp_path, capsys, failure, listing_format
):
    release = tmp_path / 'release'
    (release / 'config').mkdir(parents=True)
    revision = 'sha256:' + 'a' * 64
    (release / 'config/mac-models.json').write_text(json.dumps({
        'model': 'synthetic-model:small', 'revision': revision,
        'evaluation': {'accepted': False},
    }))
    installed = {'platform': 'macos-arm64', 'models': 'all', 'profiles': ['ai', 'transcription']}
    monkeypatch.setattr(mac.node, '_installed_release', lambda _: (installed, release))
    monkeypatch.setattr(mac.node, '_dotenv', lambda _: {
        'RECORDBENCH_TLS_CERT': str(tmp_path / 'synthetic.crt'),
        'RECORDBENCH_HTTPS_PORT': '9443',
    })
    tls_context = object()
    monkeypatch.setattr(mac.ssl, 'create_default_context', lambda **kwargs: tls_context)
    health = {
        'product': 'RecordBench', 'status': 'ok', 'storage': {'status': 'ready'},
        'capabilities': {'answering': 'ready', 'search': 'word + meaning',
                         'transcription': 'local WhisperX'},
    }

    def response(url, **kwargs):
        if url.endswith('/health'):
            assert kwargs['context'] is tls_context
            value = health
        else:
            assert url == 'http://127.0.0.1:11435/api/tags'
            value = {'models': [{'name': 'synthetic-model:small',
                                 'digest': ('b' * 64 if failure == 'wrong_artifact' else revision)}]}
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(mac.urllib.request, 'urlopen', response)
    rows = [{'Service': name, 'State': 'running', 'Health': ''} for name in (
        'app', 'gateway', 'postgres', 'clamav', 'clamav-updater', 'retrieval',
        'transcription-api', 'transcription-worker', 'transcription-cleanup-daemon',
    )]
    if failure == 'missing_worker':
        rows = [row for row in rows if row['Service'] != 'transcription-worker']
    if failure == 'stopped_worker':
        next(row for row in rows if row['Service'] == 'transcription-worker')['State'] = 'exited'
    if failure == 'unhealthy_service':
        next(row for row in rows if row['Service'] == 'retrieval')['Health'] = 'unhealthy'
    listing = json.dumps(rows) if listing_format == 'array' else '\n'.join(json.dumps(row) for row in rows)
    monkeypatch.setattr(mac.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=listing))
    assert mac.doctor(tmp_path) == (0 if failure is None else 1)
    result = json.loads(capsys.readouterr().out)
    assert result['ready'] is (failure is None)
    assert result['qualification'] == 'experimental'
    assert result['generator']['quality_accepted'] is False
    if failure == 'missing_worker':
        assert result['services']['transcription-worker'] == 'missing'


def test_interrupted_configuration_cannot_launch_and_can_resume(monkeypatch, tmp_path):
    root = tmp_path / 'node'
    monkeypatch.setattr(mac.node, '_stage_release', lambda *args, **kwargs: ('synthetic', tmp_path / 'release'))

    def fake_run(console, command, **kwargs):
        (root / 'tls/tls.key').write_text('synthetic key placeholder')
        (root / 'tls/tls.crt').write_text('synthetic cert placeholder')

    monkeypatch.setattr(mac.node, '_run', fake_run)
    original_write = mac.node._private_write
    interrupted = False

    def interrupted_write(path, value, **kwargs):
        nonlocal interrupted
        if path.name == 'recordbench.env' and 'Mac application' in value and not interrupted:
            interrupted = True
            raise OSError('synthetic interrupted write')
        return original_write(path, value, **kwargs)

    monkeypatch.setattr(mac.node, '_private_write', interrupted_write)
    with pytest.raises(OSError, match='synthetic interrupted'):
        mac.configure(root, capabilities='all', port=9443)
    assert (root / 'mac-configuration.pending').read_text() == 'macos-arm64\n'
    with pytest.raises(RuntimeError, match='incomplete'):
        mac.compose(root)
    mac.configure(root, capabilities='all', port=9443)
    assert not (root / 'mac-configuration.pending').exists()
    assert json.loads((root / 'installation.json').read_text())['platform'] == 'macos-arm64'
    assert mac.node._dotenv(root / 'config/recordbench.env')['CASE_INTELLIGENCE_GENERATOR_BACKEND'] == 'ollama'


@pytest.mark.parametrize('initialized_file', ['secrets/local-accounts.json', 'matter-storage/.recordbench-managed-storage.json'])
def test_incomplete_marker_never_reconfigures_initialized_data(tmp_path, initialized_file):
    (tmp_path / 'mac-configuration.pending').write_text('macos-arm64\n')
    initialized = tmp_path / initialized_file
    initialized.parent.mkdir(parents=True)
    initialized.write_text('{}')
    with pytest.raises(RuntimeError, match='initialized node'):
        mac.configure(tmp_path, capabilities='none', port=9443)


def test_early_directory_preparation_failure_preserves_retry_marker(monkeypatch, tmp_path):
    root = tmp_path / 'node'

    def interrupted_prepare(*args, **kwargs):
        (root / 'config').mkdir(exist_ok=True)
        raise OSError('synthetic directory preparation failure')

    monkeypatch.setattr(mac.node, '_prepare_directories', interrupted_prepare)
    for _ in range(2):
        with pytest.raises(OSError, match='directory preparation failure'):
            mac.configure(root, capabilities='none', port=9443)
        assert (root / 'mac-configuration.pending').read_text() == 'macos-arm64\n'
