"""Synthetic real-file failure cases for complete, no-clobber receipt publication."""
from __future__ import annotations

import errno
import io
import json
import os
from pathlib import Path
import stat

import pytest

from case_intelligence import claim_evaluation as evaluation


class FaultyWriter:
    def __init__(self, stream, failure, error):
        self.stream, self.failure, self.error = stream, failure, error

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        result = self.stream.__exit__(*args)
        if self.failure == "close" and args[0] is None:
            raise self.error
        return result

    def write(self, value):
        if self.failure in {"write", "interrupt"}:
            self.stream.write(value[:7])
            self.stream.flush()
            raise self.error
        return self.stream.write(value)


@pytest.mark.parametrize("failure", ["write", "close", "interrupt"])
def test_incomplete_receipt_never_reserves_final_path_and_can_retry(tmp_path, monkeypatch, failure):
    path = tmp_path / "capture.json"
    payload = {"synthetic_only": True, "completed_capture": ["first", "second"]}
    error = (KeyboardInterrupt("Synthetic interrupted receipt") if failure == "interrupt"
             else OSError(errno.ENOSPC if failure == "write" else errno.EIO, "Synthetic receipt I/O failure"))
    original_open = io.open
    opened = []

    def faulty_open(*args, **kwargs):
        stream = original_open(*args, **kwargs)
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        if "b" in mode and any(flag in mode for flag in "wx"):
            opened.append(stream)
            return FaultyWriter(stream, failure, error)
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(io, "open", faulty_open)
        with pytest.raises(type(error)) as caught:
            evaluation.write_new(path, payload)
    assert caught.value is error
    assert opened and all(stream.closed for stream in opened)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
    evaluation.write_new(path, payload)
    assert json.loads(path.read_text()) == payload
    assert list(tmp_path.iterdir()) == [path]


def test_receipt_is_published_only_after_complete_write_and_close(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    payload = {"synthetic_only": True, "text": "café\nrecord"}
    expected = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    original_open, original_link = io.open, os.link
    streams, installed = [], []

    def track_open(*args, **kwargs):
        stream = original_open(*args, **kwargs)
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        if "b" in mode and any(flag in mode for flag in "wx"):
            streams.append(stream)
        return stream

    def inspect_install(source, destination, *args, **kwargs):
        source = Path(source)
        assert source.parent == path.parent
        assert Path(destination) == path and not path.exists()
        assert streams and all(stream.closed for stream in streams)
        assert source.read_bytes() == expected
        assert stat.S_IMODE(source.stat().st_mode) == 0o600
        original_link(source, destination, *args, **kwargs)
        installed.append(True)

    monkeypatch.setattr(io, "open", track_open)
    monkeypatch.setattr(os, "link", inspect_install)
    evaluation.write_new(path, payload)
    assert installed == [True]
    assert path.read_bytes() == expected
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("existing", ["file", "symlink", "directory"])
def test_receipt_never_replaces_preexisting_destination(tmp_path, existing):
    path = tmp_path / "capture.json"
    original = b"Synthetic prior output remains exact.\n"
    other = tmp_path / "original.json"
    if existing == "file":
        path.write_bytes(original)
    elif existing == "symlink":
        other.write_bytes(original)
        path.symlink_to(other.name)
    else:
        path.mkdir()
        (path / "original.txt").write_bytes(original)
    before_names = set(tmp_path.iterdir())
    before_stat = path.lstat()
    with pytest.raises(FileExistsError):
        evaluation.write_new(path, {"replacement": False})
    assert path.lstat().st_ino == before_stat.st_ino
    assert set(tmp_path.iterdir()) == before_names
    if existing == "directory":
        assert (path / "original.txt").read_bytes() == original
    else:
        assert path.read_bytes() == original
        assert path.is_symlink() == (existing == "symlink")


def test_racing_creator_wins_without_receipt_clobber_or_temp_leak(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    original_link = os.link
    winner = b"Synthetic concurrent receipt.\n"

    def concurrent_install(source, destination, *args, **kwargs):
        with path.open("xb") as stream:
            stream.write(winner)
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", concurrent_install)
    with pytest.raises(FileExistsError):
        evaluation.write_new(path, {"replacement": False})
    assert path.read_bytes() == winner
    assert list(tmp_path.iterdir()) == [path]


def test_failed_atomic_install_removes_only_owned_temp_and_allows_retry(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    retained = tmp_path / ".claim-receipt-existing"
    retained.write_bytes(b"Synthetic unrelated file.")
    error = OSError(errno.EACCES, "Synthetic install refused")

    def fail_install(*args, **kwargs):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail_install)
        with pytest.raises(OSError) as caught:
            evaluation.write_new(path, {"retained": True})
    assert caught.value is error
    assert not path.exists() and list(tmp_path.iterdir()) == [retained]
    assert retained.read_bytes() == b"Synthetic unrelated file."
    evaluation.write_new(path, {"retained": True})
    assert json.loads(path.read_text()) == {"retained": True}
    assert set(tmp_path.iterdir()) == {path, retained}


def test_fsync_failure_does_not_publish_receipt(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    error = OSError(errno.ENOSPC, "Synthetic delayed write failure")
    original_fsync = os.fsync

    def fail_fsync(fd):
        original_fsync(fd)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_fsync)
        with pytest.raises(OSError) as caught:
            evaluation.write_new(path, {"retained": True})
    assert caught.value is error
    assert not path.exists() and list(tmp_path.iterdir()) == []
    evaluation.write_new(path, {"retained": True})
    assert json.loads(path.read_text()) == {"retained": True}


def test_cleanup_failure_preserves_original_error_and_other_files(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    original = tmp_path / "original.json"
    original.write_bytes(b"Synthetic unrelated receipt.")
    primary = OSError(errno.ENOSPC, "Synthetic sync failure")
    cleanup = OSError(errno.EACCES, "Synthetic cleanup failure")
    original_unlink = Path.unlink

    def fail_sync(fd):
        raise primary

    def fail_owned_cleanup(candidate, *args, **kwargs):
        assert candidate.parent == tmp_path and candidate.name.startswith(".claim-receipt-")
        raise cleanup

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_sync)
        patch.setattr(Path, "unlink", fail_owned_cleanup)
        with pytest.raises(OSError) as caught:
            evaluation.write_new(path, {"retained": True})
    assert caught.value is primary
    assert not path.exists() and original.read_bytes() == b"Synthetic unrelated receipt."
    leftovers = [p for p in tmp_path.iterdir() if p != original]
    assert len(leftovers) == 1 and stat.S_IMODE(leftovers[0].stat().st_mode) == 0o600
    original_unlink(leftovers[0])


def test_cleanup_failure_after_install_retains_complete_noclobber_receipt(tmp_path, monkeypatch):
    path = tmp_path / "capture.json"
    payload = {"synthetic_only": True, "retained": True}
    cleanup = OSError(errno.EACCES, "Synthetic cleanup failure")

    def fail_owned_cleanup(candidate, *args, **kwargs):
        assert candidate != path and candidate.name.startswith(".claim-receipt-")
        raise cleanup

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_owned_cleanup)
        with pytest.raises(OSError) as caught:
            evaluation.write_new(path, payload)
    assert caught.value is cleanup
    assert json.loads(path.read_text()) == payload
    with pytest.raises(FileExistsError):
        evaluation.write_new(path, {"replacement": False})
    assert json.loads(path.read_text()) == payload
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert len(leftovers) == 1 and leftovers[0].read_bytes() == path.read_bytes()
    leftovers[0].unlink()
