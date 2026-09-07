#!/usr/bin/env python3
"""Create the shared development environment used by the local quality gates."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = (3, 12)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a virtual environment and install all test dependencies."
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=ROOT / ".venv",
        help="virtual-environment directory (default: .venv)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to create the environment",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands without creating or modifying an environment",
    )
    return parser


def bootstrap(*, venv: Path, python: str, dry_run: bool) -> list[list[str]]:
    venv = venv.expanduser().resolve()
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    environment_python = venv / bin_dir / ("python.exe" if os.name == "nt" else "python")
    commands = [
        [python, "-m", "venv", str(venv)],
        [str(environment_python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(environment_python), "-m", "pip", "install", "-e", ".[dev,postgres]"],
        [
            str(environment_python),
            "-m",
            "pip",
            "install",
            "-e",
            "./services/transcription[dev]",
        ],
    ]
    for command in commands:
        print("+", " ".join(command))
        if not dry_run:
            subprocess.run(command, cwd=ROOT, check=True)
    return commands


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise SystemExit(f"bootstrap requires Python {required} or newer")
    bootstrap(venv=args.venv, python=args.python, dry_run=args.dry_run)
    print(f"Development environment ready at {args.venv.expanduser().resolve()}")
    print("Next: make check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
