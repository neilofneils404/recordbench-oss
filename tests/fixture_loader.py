from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures" / "synthetic" / "two_matter" / "v1"


def load_synthetic_fixture(*, verify_files: bool = False) -> dict:
    data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if verify_files:
        count = 0
        for matter in data["matters"]:
            for source in matter["sources"]:
                for record in (source, source["representation"]):
                    path = (ROOT / record["path"]).resolve()
                    if not path.is_relative_to(ROOT.resolve()):
                        raise ValueError("fixture path escapes root")
                    unresolved = ROOT / record["path"]
                    if unresolved.is_symlink():
                        raise ValueError("fixture paths cannot be symlinks")
                    payload = path.read_bytes()
                    assert len(payload) == record["byte_size"]
                    assert hashlib.sha256(payload).hexdigest() == record["sha256"]
                    count += 1
        data["verified_file_count"] = count
    return data
