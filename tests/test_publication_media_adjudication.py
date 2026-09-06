import hashlib
import importlib.util
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location("media_publication", Path(__file__).resolve().parents[1] / "scripts/publication-check.py")
SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCAN
SPEC.loader.exec_module(SCAN)


def inspect(data, *, name="example.mp4", digests=(), deny=(b"xyz",)):
    return SCAN._scan_content(data, name=name, location="synthetic", deny=deny,
                              reviewed_media_digests=digests)


def test_only_exact_media_bytes_receive_short_match_disposition(monkeypatch):
    monkeypatch.setattr(SCAN, "_scan_media", lambda *args, **kwargs: [])
    data = b"synthetic-compressed-xyz-marker"
    digest = hashlib.sha256(data).hexdigest()
    assert inspect(data)
    assert not inspect(data, digests=(digest,))
    assert inspect(data + b"changed", digests=(digest,))
    assert inspect(data, name="example.txt", digests=(digest,))
    assert inspect(data, deny=(b"compressed",), digests=(digest,))


def test_decoded_metadata_and_other_secret_checks_still_block(monkeypatch):
    def metadata(data, *, name, location, deny):
        return SCAN._scan_bytes(b"xyz", location=location, deny=deny)
    monkeypatch.setattr(SCAN, "_scan_media", metadata)
    data = b"synthetic-compressed-xyz-marker"
    assert inspect(data, digests=(hashlib.sha256(data).hexdigest(),))
    monkeypatch.setattr(SCAN, "_scan_media", lambda *args, **kwargs: [])
    data += b" -----BEGIN " + b"PRIVATE KEY-----"
    assert inspect(data, digests=(hashlib.sha256(data).hexdigest(),))
