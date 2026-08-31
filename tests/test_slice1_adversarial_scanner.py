from __future__ import annotations

import os

import pytest

from case_intelligence.scanner import ScanError, ScanLimits, SyntheticScanner
from tests.slice1_support import make_environment


def _fds() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.mark.parametrize(
    ("limits", "setup"),
    [
        (ScanLimits(max_aggregate_bytes=30), lambda root: None),
        (ScanLimits(max_depth=0), lambda root: None),
        (ScanLimits(max_path_bytes=8), lambda root: None),
    ],
)
def test_all_scanner_limits_fail_closed_without_fd_leaks(tmp_path, limits, setup):
    store, _, _, _, roots = make_environment(tmp_path)
    setup(roots["alpha"])
    before = _fds()
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], limits=limits).scan()
    assert _fds() == before
    store.close()


@pytest.mark.parametrize("name", ["bad.", "bad ", "CON.txt", "x:y", "bad\x01name"])
def test_scanner_rejects_windows_unsafe_and_control_names(tmp_path, name):
    store, _, _, _, roots = make_environment(tmp_path)
    (roots["alpha"] / name).write_text("unsafe", encoding="utf-8")
    before = _fds()
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"]).scan()
    assert _fds() == before
    store.close()


def test_casefold_collision_rejects_whole_scan_and_closes_fds(tmp_path):
    store, _, _, _, roots = make_environment(tmp_path)
    (roots["alpha"] / "Report.TXT").write_text("one", encoding="utf-8")
    (roots["alpha"] / "report.txt").write_text("two", encoding="utf-8")
    before = _fds()
    with pytest.raises(ScanError, match="collision"):
        SyntheticScanner(roots["alpha"]).scan()
    assert _fds() == before
    store.close()
