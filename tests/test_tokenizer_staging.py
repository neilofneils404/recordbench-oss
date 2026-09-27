"""Only synthetic archives: immutable tokenizer verification and safe extraction."""
import hashlib
import io
import stat
import zipfile

import pytest

from tests.test_nemotron_installation import stager_module


def archive_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return stream.getvalue()


def prepare(monkeypatch, data):
    module = stager_module()
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    return module, {"url": "https://example.com/synthetic.zip", "sha256": hashlib.sha256(data).hexdigest()}


def test_verified_archive_can_be_staged_again_without_changing_bytes(tmp_path, monkeypatch):
    data = archive_bytes([("punkt_tab/english/synthetic.tab", b"one\ttwo")])
    module, resource = prepare(monkeypatch, data)
    files = module._stage_tokenizer(tmp_path, resource)
    assert len(files) == 1 and files[0].read_bytes() == b"one\ttwo"
    before = files[0].stat().st_mtime_ns
    assert module._stage_tokenizer(tmp_path, resource) == files
    assert files[0].stat().st_mtime_ns == before
    files[0].write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="existing tokenizer differs"):
        module._stage_tokenizer(tmp_path, resource)
    assert files[0].read_bytes() == b"changed"


@pytest.mark.parametrize("name", ["../escaped", "/absolute", "other/file", "punkt_tab/../escaped", "punkt_tab\\escaped"])
def test_rejects_unsafe_archive_entries_before_extraction(tmp_path, monkeypatch, name):
    module, resource = prepare(monkeypatch, archive_bytes([(name, b"synthetic")]))
    with pytest.raises(RuntimeError, match="unsafe entry"):
        module._stage_tokenizer(tmp_path, resource)
    assert not list(tmp_path.iterdir())


def test_rejects_symlink_archive_entry(tmp_path, monkeypatch):
    entry = zipfile.ZipInfo("punkt_tab/link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    module, resource = prepare(monkeypatch, archive_bytes([(entry, b"outside")]))
    with pytest.raises(RuntimeError, match="unsafe entry"):
        module._stage_tokenizer(tmp_path, resource)
    assert not list(tmp_path.iterdir())


def test_hash_mismatch_is_rejected_before_opening_archive(tmp_path, monkeypatch):
    module, resource = prepare(monkeypatch, b"not a zip")
    resource["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="failed verification"):
        module._stage_tokenizer(tmp_path, resource)
    assert not list(tmp_path.iterdir())


def test_rejects_excessive_expansion(tmp_path, monkeypatch):
    module, resource = prepare(monkeypatch, archive_bytes([("punkt_tab/large", b"x" * (16 * 1024 * 1024 + 1))]))
    with pytest.raises(RuntimeError, match="extraction limits"):
        module._stage_tokenizer(tmp_path, resource)
    assert not list(tmp_path.iterdir())


def test_rejects_destination_symlink(tmp_path, monkeypatch):
    module, resource = prepare(monkeypatch, archive_bytes([("punkt_tab/file", b"synthetic")]))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "nltk_data").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        module._stage_tokenizer(tmp_path, resource)
    assert not list(elsewhere.iterdir())


def test_receipt_verifies_tokenizer_offline_and_detects_changed_file(tmp_path, monkeypatch):
    module, resource = prepare(monkeypatch, archive_bytes([("punkt_tab/english/synthetic.tab", b"synthetic")]))
    files = module._stage_tokenizer(tmp_path, resource)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"schema_version": 1}')
    groups = frozenset({"transcription-asr"})
    module._stage_receipt(tmp_path, catalog, groups, "portable", files)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: pytest.fail("offline verification used network"))
    module._verify_stage(tmp_path, catalog, groups, "portable")
    files[0].write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="missing or changed"):
        module._verify_stage(tmp_path, catalog, groups, "portable")


def test_preserves_legacy_extra_files_and_requires_fresh_root(tmp_path, monkeypatch):
    module, resource = prepare(monkeypatch, archive_bytes([("punkt_tab/file", b"synthetic")]))
    legacy = tmp_path / "nltk_data/tokenizers/punkt_tab.zip"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy artifact")
    with pytest.raises(RuntimeError, match="fresh staging root"):
        module._stage_tokenizer(tmp_path, resource)
    assert legacy.read_bytes() == b"legacy artifact"
    assert not (legacy.parent / "punkt_tab").exists()
