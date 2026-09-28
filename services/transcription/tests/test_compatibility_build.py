"""Synthetic failure boundaries for the compatibility source build."""
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "whisperx_builder", Path(__file__).resolve().parents[1] / "compatibility/build_whisperx.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def archive_at(tmp_path, name, kind=tarfile.REGTYPE):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "../escaped"
        archive.addfile(entry, io.BytesIO())
    path = tmp_path / "synthetic.tar.gz"
    path.write_bytes(stream.getvalue())
    return path


def test_wrong_source_hash_creates_no_source_tree(tmp_path):
    archive = archive_at(tmp_path, "synthetic")
    destination = tmp_path / "source"
    with pytest.raises(RuntimeError, match="identity"):
        builder.extract_source(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("name,kind", [
    ("/absolute", tarfile.REGTYPE),
    (f"whisperX-{builder.REVISION}/../escaped", tarfile.REGTYPE),
    (f"whisperX-{builder.REVISION}/link", tarfile.SYMTYPE),
    (f"whisperX-{builder.REVISION}/pipe", tarfile.FIFOTYPE),
])
def test_unsafe_tar_members_rejected_before_any_extraction(tmp_path, monkeypatch, name, kind):
    archive = archive_at(tmp_path, name, kind)
    monkeypatch.setattr(builder, "SOURCE_SHA256", builder.sha256(archive.read_bytes()))
    destination = tmp_path / "source"
    with pytest.raises(RuntimeError, match="unsafe"):
        builder.extract_source(archive, destination)
    assert not destination.exists()


def test_metadata_patch_refuses_unknown_upstream():
    with pytest.raises(RuntimeError, match="metadata identity"):
        builder.patch_metadata(b'[project]\nname="synthetic"\n')


def test_source_fifo_fails_without_blocking(tmp_path):
    import os
    archive = tmp_path / "pipe"
    os.mkfifo(archive)
    with pytest.raises(RuntimeError, match="regular file"):
        builder.extract_source(archive, tmp_path / "output")
