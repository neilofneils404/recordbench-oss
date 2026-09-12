#!/usr/bin/env python3
"""Reject empty, skipped, or unsuccessful PostgreSQL CI test reports."""
from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def check_report(path: Path) -> int:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    if len(cases) < 7:
        raise ValueError("Expected at least seven PostgreSQL acceptance tests")
    if any(case.find(outcome) is not None for case in cases
           for outcome in ("skipped", "failure", "error")):
        raise ValueError("PostgreSQL acceptance tests must pass without skips")
    return len(cases)


if __name__ == "__main__":
    try:
        count = check_report(Path(sys.argv[1]))
    except (IndexError, OSError, ValueError, ET.ParseError) as error:
        print(f"PostgreSQL acceptance blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"PostgreSQL acceptance: {count} passed, zero skipped")
