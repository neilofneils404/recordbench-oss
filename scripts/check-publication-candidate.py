#!/usr/bin/env python3
"""Run the existing outgoing-history guard for one verified CI candidate.

Full fetches may include unrelated branches. The pre-push guard already isolates
explicit outgoing objects with all their ancestors and annotated-tag objects.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.PIPE).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--publication-ref", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", args.expected_head):
        raise ValueError("Invalid expected candidate")
    if git("rev-parse", "--verify", "HEAD") != args.expected_head:
        raise ValueError("Candidate does not match the expected head")
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not args.publication_ref.startswith(("refs/heads/", "refs/pull/", "refs/tags/")):
        raise ValueError("Invalid publication reference")
    oid = args.expected_head
    outgoing_ref = "refs/heads/publication-candidate"
    if args.publication_ref.startswith("refs/tags/"):
        if git("rev-parse", "--verify", "--end-of-options", args.publication_ref + "^{commit}") != args.expected_head:
            raise ValueError("Tag does not identify the expected candidate")
        oid = git("rev-parse", "--verify", "--end-of-options", args.publication_ref)
        outgoing_ref = args.publication_ref
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
        raise ValueError("Invalid outgoing object")
    guard = Path(__file__).with_name("pre-push-publication.py")
    if guard.is_symlink() or not guard.is_file():
        raise ValueError("Publication guard is unavailable")
    result = subprocess.run(
        [sys.executable, "-I", str(guard)],
        input=f"HEAD {oid} {outgoing_ref} {'0' * len(oid)}\n",
        text=True,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Publication blocked: the expected candidate could not be verified.", file=sys.stderr)
        raise SystemExit(1)
