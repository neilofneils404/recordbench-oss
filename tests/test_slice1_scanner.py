from __future__ import annotations

import os

import pytest

from case_intelligence.scanner import ScanError, ScanLimits, SyntheticScanner
from tests.slice1_support import make_environment


def test_scanner_is_bounded_deterministic_and_closes_descriptors(tmp_path):
    store, _, _, _, roots = make_environment(tmp_path)
    before = len(os.listdir("/proc/self/fd"))
    first = SyntheticScanner(roots["alpha"]).scan()
    second = SyntheticScanner(roots["alpha"]).scan()
    assert first == second
    assert [item.relative_path for item in first] == ["audio.wav", "image.svg", "nested/report.txt"]
    assert len(os.listdir("/proc/self/fd")) == before
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], limits=ScanLimits(max_files=2)).scan()
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], limits=ScanLimits(max_file_bytes=10)).scan()
    store.close()


def test_scanner_rejects_symlinks_nonregular_and_final_replacement(tmp_path):
    store, _, _, _, roots = make_environment(tmp_path)
    (roots["alpha"] / "bad-link").symlink_to("nested/report.txt")
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"]).scan()
    (roots["alpha"] / "bad-link").unlink()
    os.mkfifo(roots["alpha"] / "fifo")
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"]).scan()
    (roots["alpha"] / "fifo").unlink()

    target = roots["alpha"] / "nested/report.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    done = False
    def replace(stage, relative):
        nonlocal done
        if stage == "before_open" and relative == "nested/report.txt" and not done:
            done = True
            target.unlink()
            target.symlink_to(outside)
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], _test_hook=replace).scan()
    store.close()


def test_scanner_rejects_parent_move_and_hash_mutation(tmp_path):
    store, _, _, _, roots = make_environment(tmp_path)
    nested = roots["alpha"] / "nested"
    moved = tmp_path / "moved"
    done = False
    def move_parent(stage, relative):
        nonlocal done
        if stage == "before_open" and relative == "nested/report.txt" and not done:
            done = True
            nested.rename(moved)
            nested.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], _test_hook=move_parent).scan()
    nested.unlink()
    moved.rename(nested)

    target = nested / "report.txt"
    changed = False
    def mutate(stage, relative):
        nonlocal changed
        if stage == "hash_chunk" and relative == "nested/report.txt" and not changed:
            changed = True
            target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ScanError):
        SyntheticScanner(roots["alpha"], _test_hook=mutate).scan()
    store.close()


def test_scanner_rejects_mnt_without_access():
    with pytest.raises(ScanError):
        SyntheticScanner(__import__("pathlib").Path("/mnt/example"))
