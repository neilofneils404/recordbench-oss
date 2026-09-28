"""Copy an operator-prepared, hash-inventoried cache into a NEW offline cache.

No hub client, credentials, model code, or model deserializer is used. Failed
copies retain a partial destination without an approved manifest for diagnosis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from .asr_models import approved_asr_snapshot
from .model_manifest import (
    DEFAULT_MODEL_MANIFEST_NAME, ModelManifestError, _cache_root, _changed,
    _open_relative, _parse_manifest, _read_manifest, verify_model_manifest,
)


_FAILURE = "Local model import failed; check the inventory, capacity and new destination."


def import_model_cache(source: Path, destination: Path, *, max_bytes: int) -> dict:
    """Validate and copy only declared regular files; never merge or overwrite."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError(_FAILURE)
    root, source_fd = _cache_root(source)
    destination = Path(os.path.abspath(destination.expanduser()))
    try:
        # Operators must supply canonical paths. The source verifier additionally
        # opens each manifest/artifact component relative to the pinned root fd.
        if any(p.is_symlink() for p in (root, *root.parents, destination, *destination.parents)):
            raise ValueError(_FAILURE)
        if destination.is_relative_to(root) or root.is_relative_to(destination):
            raise ValueError(_FAILURE)
        if destination.exists() or not destination.parent.is_dir():
            raise ValueError(_FAILURE)
        content = _read_manifest(source_fd, (DEFAULT_MODEL_MANIFEST_NAME,))
        _, artifacts, bindings = _parse_manifest(content)
        files = {f.parts: f for artifact in artifacts for f in artifact.files}
        if ((DEFAULT_MODEL_MANIFEST_NAME,) in files
                or (".pending-model-manifest.json",) in files):
            raise ValueError(_FAILURE)
        total = sum(f.size_bytes for f in files.values()) + len(content)
        if total > max_bytes or total > shutil.disk_usage(destination.parent).free:
            raise ValueError(_FAILURE)
        ready = verify_model_manifest(root, root / DEFAULT_MODEL_MANIFEST_NAME)
        if ready.manifest_sha256 != hashlib.sha256(content).hexdigest():
            raise ValueError(_FAILURE)
        for binding in bindings:
            alias = "large-v3" if binding.slot == "primary" else "turbo"
            snapshot = approved_asr_snapshot(root, ready, alias)
            if any(path.is_symlink() for path in snapshot.rglob("*")):
                raise ValueError(_FAILURE)
        destination.mkdir(mode=0o700, exist_ok=False)
        for parts, expected in sorted(files.items()):
            fd = _open_relative(source_fd, parts, missing_code="artifact_missing",
                                symlink_code="artifact_symlink", unreadable_code="artifact_unreadable")
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_size != expected.size_bytes:
                    raise ValueError(_FAILURE)
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                out_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                digest, remaining = hashlib.sha256(), expected.size_bytes
                with os.fdopen(out_fd, "wb") as output:
                    while remaining:
                        block = os.read(fd, min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError(_FAILURE)
                        digest.update(block)
                        output.write(block)
                        remaining -= len(block)
                    if os.read(fd, 1) or _changed(before, os.fstat(fd)) or digest.hexdigest() != expected.sha256:
                        raise ValueError(_FAILURE)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                os.close(fd)
        pending = destination / ".pending-model-manifest.json"
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        result = verify_model_manifest(destination, pending)
        for binding in bindings:
            approved_asr_snapshot(destination, result, "large-v3" if binding.slot == "primary" else "turbo")
        # The cache is usable only after every destination byte verifies. link()
        # refuses an existing target; unlike replace(), it never overwrites it.
        os.link(pending, destination / DEFAULT_MODEL_MANIFEST_NAME, follow_symlinks=False)
        pending.unlink()
        return result.public_dict()
    except (OSError, ValueError):
        raise ValueError(_FAILURE) from None
    finally:
        os.close(source_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Prepared cache containing approved-model-manifest.json")
    parser.add_argument("destination", type=Path, help="New cache directory; existing destinations are refused")
    parser.add_argument("--max-bytes", type=int, required=True, help="Maximum total copied bytes including manifest")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(import_model_cache(args.source, args.destination, max_bytes=args.max_bytes), sort_keys=True))
    except (ValueError, ModelManifestError):
        print(json.dumps({"status": "not_ready", "code": "model_import_failed", "message": _FAILURE}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
