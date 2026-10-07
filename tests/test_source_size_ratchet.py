"""Keep source modules from regrowing while the workbench and store are split.

Counts include blank lines, comments, and a final line without a newline. After
shrinking a module, lower its entry in snapshots/source_line_counts.json to the
reported count; remove entries for deleted modules. Do not raise existing limits.
New modules have a 1,500-line ceiling until recorded in the baseline.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).parent / "snapshots" / "source_line_counts.json"
NEW_FILE_LIMIT = 1_500


def test_source_size_ratchet():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        with path.open(encoding="utf-8") as source:
            current[path.relative_to(ROOT).as_posix()] = sum(1 for _ in source)

    failures = []
    for path, lines in current.items():
        if path not in baseline:
            if lines > NEW_FILE_LIMIT:
                failures.append(
                    f"{path}: new file has {lines:,} lines; limit is "
                    f"{NEW_FILE_LIMIT:,}. Split it into smaller modules."
                )
        elif lines > baseline[path]:
            failures.append(
                f"{path}: grew from {baseline[path]:,} to {lines:,} lines. "
                "Extract or reduce code instead of raising its baseline."
            )
        elif lines < baseline[path]:
            failures.append(
                f"{path}: shrank from {baseline[path]:,} to {lines:,} lines. "
                f"Lower its baseline to {lines} in tests/snapshots/source_line_counts.json."
            )

    for path in sorted(baseline.keys() - current.keys()):
        failures.append(
            f"{path}: file was removed. Remove its entry from "
            "tests/snapshots/source_line_counts.json."
        )

    assert not failures, "Source size ratchet failed:\n" + "\n".join(failures)
