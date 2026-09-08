#!/usr/bin/env python3
"""Create the development environment used by the local quality gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = (3, 12)
PROBE = (
    'import json, os, sys; print(json.dumps({'
    '"version": list(sys.version_info[:2]), '
    '"base_executable": os.path.realpath(sys._base_executable), '
    '"is_venv": sys.prefix != sys.base_prefix}))'
)


def environment_interpreter(venv: Path) -> Path:
    return venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def inspect_python(python: str) -> dict:
    try:
        result = subprocess.run([python, '-I', '-c', PROBE], check=True,
                                capture_output=True, text=True, timeout=15)
        info = json.loads(result.stdout)
        if tuple(info['version']) != SUPPORTED_PYTHON:
            raise ValueError('The shared development environment requires Python 3.12 '
                             '(the transcription package does not support 3.13+).')
        if not isinstance(info['base_executable'], str) or not isinstance(info['is_venv'], bool):
            raise KeyError('invalid interpreter metadata')
        return info
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError('Could not inspect the Python interpreter. Install Python 3.12 '
                         'with venv support and select it with --python.') from exc


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command)


def bootstrap(*, venv: Path, python: str, dry_run: bool) -> list[list[str]]:
    venv = venv.expanduser().absolute()
    if venv.is_symlink():
        raise ValueError('Choose a virtual environment directory that is not a symlink.')
    selected = inspect_python(python)
    environment_python = environment_interpreter(venv)
    commands = []
    if venv.exists() and (not venv.is_dir() or any(venv.iterdir())):
        if not (venv / 'pyvenv.cfg').is_file():
            raise ValueError('The destination is not a virtual environment. '
                             'Choose a new directory with --venv; existing files were preserved.')
        try:
            existing = inspect_python(str(environment_python))
        except ValueError as exc:
            raise ValueError('The existing virtual environment is incompatible. '
                             'Choose a different --venv directory; existing files were preserved.') from exc
        if not existing['is_venv'] or existing['base_executable'] != selected['base_executable']:
            raise ValueError('The existing virtual environment uses a different interpreter. '
                             'Choose a new --venv directory; existing files were preserved.')
    else:
        commands.append([python, '-m', 'venv', str(venv)])
    commands.extend([
        [str(environment_python), '-m', 'pip', 'install', '--upgrade', 'pip'],
        [str(environment_python), '-m', 'pip', 'install', '-e', '.[dev,postgres]',
         '-e', './services/transcription[dev]'],
        [str(environment_python), '-m', 'pip', 'check'],
    ])
    for command in commands:
        print('+', command_text(command), flush=True)
        if not dry_run:
            subprocess.run(command, cwd=ROOT, check=True)
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', type=Path, default=ROOT / '.venv',
                        help='environment directory (default: repository .venv)')
    parser.add_argument('--python', default=sys.executable,
                        help='Python 3.12 interpreter used to create the environment')
    parser.add_argument('--dry-run', action='store_true',
                        help='inspect interpreters and print commands without changing the environment')
    args = parser.parse_args(argv)
    try:
        bootstrap(venv=args.venv, python=args.python, dry_run=args.dry_run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print('Bootstrap did not finish. Check the command output above, fix the '
              'reported prerequisite or download problem, then rerun the same command.', file=sys.stderr)
        return 1
    if args.dry_run:
        print('Preview only: no environment was created or changed. Rerun without --dry-run to install.')
    else:
        venv = args.venv.expanduser().absolute()
        print(f'Development environment ready at {venv}')
        print('From the repository root, run: ' + command_text(
            ['make', 'check', f'PYTHON={environment_interpreter(venv)}']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
