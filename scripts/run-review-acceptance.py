#!/usr/bin/env python3
"""Run the frozen synthetic Review acceptance pack by reportable category."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks/review-acceptance-v1.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.review_acceptance.integrity import (  # noqa: E402
    PackIntegrityError,
    verify_pack_integrity,
)


def _load() -> dict[str, object]:
    payload = json.loads(PACK.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 2:
        raise SystemExit("review acceptance pack schema is unsupported")
    try:
        content_fingerprint = verify_pack_integrity(ROOT, payload)
    except PackIntegrityError as exc:
        raise SystemExit(str(exc)) from exc
    payload["verified_content_fingerprint"] = content_fingerprint
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    payload = _load()
    cases = tuple(payload["cases"])
    requested = set(args.category)
    if requested:
        known = {str(case["category"]) for case in cases}
        unknown = requested - known
        if unknown:
            raise SystemExit("unknown categories: " + ", ".join(sorted(unknown)))
        cases = tuple(case for case in cases if case["category"] in requested)
    if args.list:
        for case in cases:
            print(f"{case['category']}\t{case['case_id']}")
        return 0

    results: list[dict[str, object]] = []
    environment = os.environ.copy()
    source_root = str(ROOT / "src")
    caller_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_root + (os.pathsep + caller_pythonpath if caller_pythonpath else "")
    )
    for case in cases:
        started = time.monotonic()
        print(f"\n[{case['category']}] {case['case_id']}", flush=True)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *case["node_ids"]],
            cwd=ROOT,
            env=environment,
            check=False,
        )
        results.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "passed": completed.returncode == 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        )
    report = {
        "schema_version": 2,
        "pack_id": payload["pack_id"],
        "case_fingerprint": payload["case_fingerprint"],
        "content_fingerprint": payload["verified_content_fingerprint"],
        "passed": all(item["passed"] for item in results),
        "results": results,
    }
    print(json.dumps(report, indent=2))
    if args.json_output:
        args.json_output.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
