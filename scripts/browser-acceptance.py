#!/usr/bin/env python3
"""Run generated browser journeys with bounded lifetime and explicit receipts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BROWSER_VERSION = "152.0.7977.82"


def stop_group(process: subprocess.Popen) -> None:
    """Reap the command and stop browser/driver descendants it may have left."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def run_journey(command: list[str], *, output: Path, receipt_name: str,
                minimum_checks: int, timeout: float) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    timed_out = False
    return_code = None
    problem = ""
    checks = 0
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
        CASE_INTELLIGENCE_STORAGE_RESERVE_GIB="0")
    with (output / "runner.log").open("w") as log:
        process = subprocess.Popen(command, cwd=output, env=environment,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                problem = "Browser journey exceeded its time limit."
        finally:
            stop_group(process)
    if not problem and return_code != 0:
        problem = "Browser journey command failed."
    receipt = output / receipt_name
    if not problem:
        try:
            if receipt.is_symlink() or receipt.stat().st_size > 128 * 1024:
                raise ValueError("Invalid receipt file")
            data = json.loads(receipt.read_text())
            items = data.get("checks")
            if (data.get("synthetic_only") is not True or data.get("passed") is not True
                    or not isinstance(items, list) or len(items) < minimum_checks
                    or any(not isinstance(item, str) or not item.strip() for item in items)):
                raise ValueError("Incomplete receipt")
            checks = len(items)
        except (OSError, ValueError, AttributeError):
            problem = "Browser journey did not produce a complete passing receipt."
    result = {"passed": not problem, "checks": checks, "problem": problem,
        "return_code": return_code, "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - started, 2)}
    (output / "runner-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome-binary", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per journey (1–600)")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("Timeout must be between 1 and 600 seconds.")
    for executable in (args.chrome_binary, args.chromedriver):
        if executable.is_symlink() or not executable.is_file():
            parser.error("Provide regular browser and driver executable files.")
        result = subprocess.run([str(executable.absolute()), "--version"],
            capture_output=True, text=True, check=True, timeout=15)
        version = re.search(r"\b\d+\.\d+\.\d+\.\d+\b", result.stdout)
        if version is None or version.group() != BROWSER_VERSION:
            parser.error(f"Browser and driver must both be the pinned version {BROWSER_VERSION}.")
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error("Output directory must be new; keep earlier results separately.")
    output.mkdir(parents=True)
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    results = []
    for name, script, receipt, minimum, extra in (
        ("intake", "browser-accept-intake-receipts.py", "receipt-browser-result.json", 11, []),
        ("reports", "browser-accept-reports-bundle.py", "receipt.json", 11, ["--verify-readiness"]),
    ):
        destination = output / name
        command = [sys.executable, str(ROOT / "scripts" / script),
            "--chrome-binary", str(args.chrome_binary.absolute()),
            "--chromedriver", str(args.chromedriver.absolute()),
            "--output", str(destination), *extra]
        result = run_journey(command, output=destination, receipt_name=receipt,
            minimum_checks=minimum, timeout=args.timeout)
        results.append({"journey": name, **result})
        print(json.dumps(results[-1]), flush=True)
    summary = {"synthetic_only": True, "browser_version": BROWSER_VERSION,
        "passed": all(item["passed"] for item in results), "journeys": results}
    (output / "browser-result.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
