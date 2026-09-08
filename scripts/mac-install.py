#!/usr/bin/env python3
"""Experimental, local-only Apple Silicon node orchestration.

Keep the application in ARM64 Linux containers; use the separately pinned native
Ollama runtime for generation. Never point the Linux updater at this node.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import recordbench_install as node

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "RecordBench"


def checked_root(value: Path) -> Path:
    value = value.expanduser()
    if not value.is_absolute() or value in {Path('/'), Path.home()}:
        raise RuntimeError("choose an absolute, dedicated node directory")
    if any(p.is_symlink() for p in (value, *value.parents)):
        raise RuntimeError("node directory cannot traverse symbolic links")
    root = value.resolve()
    if root == node.PROJECT or node.PROJECT in root.parents or root in node.PROJECT.parents:
        raise RuntimeError("node state must be outside the source repository")
    return root


def compose(root: Path, *, tools: bool = False) -> list[str]:
    if (root / 'mac-configuration.pending').exists():
        raise RuntimeError('configuration is incomplete; rerun the configure command')
    installed, release = node._installed_release(root)
    if installed.get('platform') != 'macos-arm64':
        raise RuntimeError("this is not a Mac installation")
    command = ['docker', '--context', 'colima-recordbench', 'compose',
               '--env-file', str(root / 'compose.env'), '-f', str(release / 'compose.macos.yaml')]
    for profile in installed['profiles']:
        command += ['--profile', profile]
    if tools:
        command += ['--profile', 'tools']
    return command


def docker_environment() -> dict[str, str]:
    """Use the selected node's files instead of another deployment's exports."""
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith(('RECORDBENCH_', 'COMPOSE_'))
        and key not in {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'}
    }


def run(command: list[str], *, input_value: str | None = None) -> None:
    environment = docker_environment() if Path(command[0]).name == 'docker' else None
    subprocess.run(command, check=True, input=input_value, text=True, env=environment)


def vm_command(root: Path) -> list[str]:
    return ['colima', 'start', 'recordbench', '--vm-type', 'vz', '--arch', 'aarch64',
            '--cpu', '4', '--memory', '12', '--disk', '40', '--root-disk', '12',
            '--runtime', 'docker', '--activate=false', '--ssh-config=false',
            '--mount', f'{root}:w', '--mount-type', 'virtiofs']


def configure(root: Path, *, capabilities: str, port: int) -> None:
    pending = root / 'mac-configuration.pending'
    resuming = pending.is_file() and not pending.is_symlink()
    if resuming and pending.read_text() != 'macos-arm64\n':
        raise RuntimeError('unrecognized incomplete configuration marker')
    if resuming and ((root / 'secrets/local-accounts.json').exists() or (root / 'matter-storage/.recordbench-managed-storage.json').exists()):
        raise RuntimeError('cannot reconfigure an initialized node')
    if (root / 'installation.json').exists() and not resuming:
        raise RuntimeError("node already configured; use build/start/doctor/stop; updates require review")
    if root.exists() and not resuming and any(p.name != 'models' for p in root.iterdir()):
        raise RuntimeError("new node directory must be empty except for its staged models")
    console = node.Console(color=False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    node._private_write(pending, 'macos-arm64\n', replace=resuming)
    paths = node._prepare_directories(console, root, storage_root=None, resume=True, dry_run=False)
    release_id, release = node._stage_release(console, root, dry_run=False)
    args = node._parser().parse_args([
        '--root', str(root), '--auth', 'local', '--models', 'none',
        '--server-name', 'localhost', '--bind-address', '127.0.0.1',
        '--https-port', str(port), '--non-interactive', '--no-color',
        '--admin-username', 'recordbench.admin', '--admin-display-name', 'Local Administrator'])
    node._configure(console, args, root, paths, release_id, release, ())
    profiles = ['ai'] if capabilities in {'review', 'all'} else []
    if capabilities == 'all':
        profiles.append('transcription')
    app = node._dotenv(paths['config'] / 'recordbench.env')
    app.update({
        'CASE_INTELLIGENCE_GENERATOR_BACKEND': 'ollama' if profiles else '',
        'CASE_INTELLIGENCE_GENERATOR_URL': 'http://host.docker.internal:11435',
        'CASE_INTELLIGENCE_GENERATOR_MODEL': 'qwen3.5:4b',
        'CASE_INTELLIGENCE_GENERATOR_CONTEXT': '16384',
        'CASE_INTELLIGENCE_GENERATOR_MAX_OUTPUT_TOKENS': '1200',
        'CASE_INTELLIGENCE_GENERATOR_MAX_REVIEW_TOKENS': '400',
        'CASE_INTELLIGENCE_GENERATOR_TIMEOUT': '300',
        'CASE_INTELLIGENCE_GENERATION_CONCURRENCY': '1',
        'CASE_INTELLIGENCE_INGESTION_WORKERS': '1',
        'CASE_INTELLIGENCE_ANSWER_WORKERS': '1',
        'CASE_INTELLIGENCE_FULL_REVIEW_SOURCE_CONCURRENCY': '1',
        'CASE_INTELLIGENCE_MATTER_QUOTA_GIB': '10',
        'CASE_INTELLIGENCE_UPLOAD_COLLECTION_GIB': '5',
        'CASE_INTELLIGENCE_MEDIA_FILE_GIB': '2',
        'CASE_INTELLIGENCE_STORAGE_RESERVE_GIB': '15',
        'CASE_INTELLIGENCE_TRANSCRIPTION_URL': 'http://transcription-api:8510' if capabilities == 'all' else '',
    })
    node._private_write(paths['config'] / 'recordbench.env', node._env_text(app, 'Mac application'), replace=True)
    transcription = node._dotenv(paths['config'] / 'transcription.env')
    transcription.update({
        'TRANSCRIPTION_V2_PIPELINE': 'whisperx', 'TRANSCRIPTION_V2_DEVICE': 'cpu',
        'TRANSCRIPTION_V2_CPU_COMPUTE_TYPE': 'int8',
        'TRANSCRIPTION_V2_MIN_FREE_DISK_BYTES': str(15 * 1024**3),
        'TRANSCRIPTION_V2_MAX_UPLOAD_BYTES': str(2 * 1024**3),
        'TRANSCRIPTION_V2_MAX_BATCH_UPLOAD_BYTES': str(5 * 1024**3),
        'TRANSCRIPTION_V2_MAX_RETAINED_BYTES_PER_OWNER': str(10 * 1024**3),
        'TRANSCRIPTION_V2_MAX_RETAINED_BYTES_GLOBAL': str(15 * 1024**3),
    })
    node._private_write(paths['config'] / 'transcription.env', node._env_text(transcription, 'Mac transcription'), replace=True)
    environment = node._dotenv(root / 'compose.env')
    environment['COMPOSE_PROFILES'] = ','.join(profiles)
    environment['RECORDBENCH_RETRIEVAL_DEVICE'] = 'cpu'
    node._private_write(root / 'compose.env', node._env_text(environment, 'Mac Compose'), replace=True)
    installed = json.loads((root / 'installation.json').read_text())
    installed.update(platform='macos-arm64', models=capabilities, profiles=profiles,
                     gpu_layout='apple-silicon', review_model_profile='mac-qwen35-4b')
    node._private_write(root / 'installation.json', json.dumps(installed, indent=2) + '\n', replace=True)
    pending.unlink()


def initialize(root: Path, *, generate_password: bool) -> None:
    command = compose(root, tools=True)
    if not (root / 'matter-storage/.recordbench-managed-storage.json').exists():
        run([*command, 'run', '--rm', '--no-deps', 'account-admin', 'storage', 'init',
             '--root', '/var/lib/recordbench/matter-storage'])
    if not (root / 'secrets/local-accounts.json').exists():
        if generate_password:
            password = node._secret(root / 'secrets/initial-admin-password', size=24)
        else:
            import getpass
            password = getpass.getpass('New administrator password (14+ characters): ')
            if password != getpass.getpass('Confirm password: '):
                raise RuntimeError('passwords did not match')
        try:
            run([*command, 'run', '--rm', '--no-deps', '-T', 'account-admin', 'accounts', 'init',
                 '--file', '/run/recordbench-secrets/local-accounts.json', '--username', 'recordbench.admin',
                 '--display-name', 'Local Administrator', '--password-stdin'], input_value=password + '\n')
        finally:
            password = ''


def doctor(root: Path) -> int:
    installed, release = node._installed_release(root)
    environment = node._dotenv(root / 'compose.env')
    context = ssl.create_default_context(cafile=environment['RECORDBENCH_TLS_CERT'])
    url = f"https://localhost:{environment['RECORDBENCH_HTTPS_PORT']}/health"
    with urllib.request.urlopen(url, context=context, timeout=15) as response:
        health = json.load(response)
    selected = installed['models']
    ready = health.get('product') == 'RecordBench' and health.get('status') in {'ok', 'degraded'} and health.get('storage', {}).get('status') == 'ready' and node._selected_capabilities_ready(health, selected)
    process = subprocess.run([*compose(root), 'ps', '--format', 'json'], check=True, capture_output=True, text=True,
                             env=docker_environment())
    raw = process.stdout.strip()
    rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
    required = {'app', 'gateway', 'postgres', 'clamav', 'clamav-updater'}
    if selected in {'review', 'all'}:
        required.add('retrieval')
    if selected == 'all':
        required.update({'transcription-api', 'transcription-worker', 'transcription-cleanup-daemon'})
    services = {name: 'missing' for name in sorted(required)}
    for row in rows:
        if row.get('Service') in required:
            services[row['Service']] = 'ready' if row.get('State') == 'running' and row.get('Health', '') in {'', 'healthy'} else 'not_ready'
    ready = ready and all(status == 'ready' for status in services.values())
    model_status = {'required': selected in {'review', 'all'}}
    if model_status['required']:
        model = json.loads((release / 'config/mac-models.json').read_text())
        with urllib.request.urlopen('http://127.0.0.1:11435/api/tags', timeout=10) as response:
            inventory = json.loads(response.read(1_048_577))
        matches = any(item.get('name') == model['model'] and item.get('digest') in {
            model['revision'], model['revision'].removeprefix('sha256:')
        } for item in inventory.get('models', []))
        model_status.update(artifact_matches=matches, model=model['model'],
                            quality_accepted=model.get('evaluation', {}).get('accepted', False))
        ready = ready and matches
    print(json.dumps({'platform': 'macos-arm64', 'requested': selected, 'ready': ready,
                      'qualification': 'experimental', 'generator': model_status,
                      'services': services,
                      'health': health}, indent=2))
    return 0 if ready else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'vm', 'configure', 'build', 'init', 'stage-models', 'start', 'stop', 'doctor'))
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--capabilities', choices=('none', 'review', 'all'), default='all')
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--generate-password', action='store_true', help='store a generated initial password in the private node secrets directory')
    args = parser.parse_args()
    try:
        root = checked_root(args.root)
        if not 1024 <= args.port <= 65535:
            raise RuntimeError('HTTPS port must be between 1024 and 65535')
        if args.command == 'plan':
            print(json.dumps({'status': 'experimental', 'root': str(root), 'vm_command': vm_command(root),
                              'capabilities': args.capabilities, 'host_generator': '127.0.0.1:11435',
                              'runtime': 'ARM64 Linux core, native Ollama Metal generator'}, indent=2))
            return 0
        if platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise RuntimeError('this launcher requires native Apple Silicon macOS')
        if args.command == 'vm':
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            run(vm_command(root))
        elif args.command == 'configure':
            configure(root, capabilities=args.capabilities, port=args.port)
        elif args.command == 'build':
            run([*compose(root, tools=True), 'build'])
        elif args.command == 'init':
            initialize(root, generate_password=args.generate_password)
        elif args.command == 'stage-models':
            installed, _ = node._installed_release(root)
            groups = ['review'] if installed['models'] in {'review', 'all'} else []
            if installed['models'] == 'all':
                groups += ['transcription-asr', 'transcription-alignment-en']
            if groups:
                run([*compose(root, tools=True), 'run', '--rm', '--no-deps', '-T',
                     'model-stager', 'stage', '--groups', ','.join(groups), '--retrieval-only'])
        elif args.command == 'start':
            run([*compose(root), 'up', '-d'])
        elif args.command == 'stop':
            run([*compose(root), 'stop'])
        elif args.command == 'doctor':
            return doctor(root)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Mac setup: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
