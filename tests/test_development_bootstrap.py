from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap-dev.py"


def test_bootstrap_dry_run_covers_both_editable_projects(tmp_path: Path) -> None:
    environment = tmp_path / "recordbench-dev"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--venv", str(environment), "--dry-run"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not environment.exists()
    assert "-m venv" in result.stdout
    assert "-e .[dev,postgres]" in result.stdout
    assert "-e ./services/transcription[dev]" in result.stdout
    assert "Next: make check" in result.stdout


def test_makefile_exposes_bootstrap_with_configurable_python() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "SYSTEM_PYTHON ?= python3" in makefile
    assert "bootstrap:" in makefile
    assert "$(SYSTEM_PYTHON) scripts/bootstrap-dev.py" in makefile
