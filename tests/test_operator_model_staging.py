"""Reference acquisition preserves operator-selected inventories before downloads."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("schema", ["transcription-v2-model-manifest-v2", "unknown", None])
def test_reference_staging_refuses_custom_or_unknown_inventory(tmp_path, monkeypatch, schema):
    script = Path(__file__).resolve().parents[1] / "scripts/stage-models.py"
    spec = importlib.util.spec_from_file_location("operator_staging_fixture", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = tmp_path / "huggingface/hub"
    cache.mkdir(parents=True)
    manifest = cache / "approved-model-manifest.json"
    original = json.dumps({"schema_version": schema, "artifacts": []}).encode()
    manifest.write_bytes(original)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        snapshot_download=lambda **kw: pytest.fail("download before custom inventory guard")))
    monkeypatch.setattr(sys, "argv", ["stage-models", "--model-root", str(tmp_path),
                                     "--catalog", str(tmp_path / "does-not-exist.json")])
    with pytest.raises(RuntimeError, match="cannot replace"):
        module.main()
    assert manifest.read_bytes() == original
    with pytest.raises(RuntimeError, match="cannot replace"):
        module._write_manifest(cache, [])
    assert manifest.read_bytes() == original
