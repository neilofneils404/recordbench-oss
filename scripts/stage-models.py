#!/usr/bin/env python3
"""Stage pinned model snapshots and write the offline transcription manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Iterable, Mapping


TRANSCRIPTION_SCHEMA = "transcription-v2-model-manifest-v1"
STAGE_GROUPS = frozenset(
    {
        "review",
        "transcription-asr",
        "transcription-alignment-en",
        "transcription-alignment-es",
        "transcription-diarization",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _catalog(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("model catalog is invalid")
    return payload


def _token(args: argparse.Namespace) -> str | None:
    if not args.token_stdin:
        return None
    value = sys.stdin.readline(4097).rstrip("\r\n")
    if not value or len(value) > 4096 or any(character in value for character in "\x00"):
        raise RuntimeError("Hugging Face token input is invalid")
    return value


def _selected(
    value: Mapping[str, object],
    groups: frozenset[str],
    *,
    review_profile: str,
    retrieval_only: bool = False,
) -> bool:
    if value.get("group") not in groups:
        return False
    if value.get("group") == "review" and value.get("role") == "generator":
        if retrieval_only:
            return False
        return value.get("profile") == review_profile
    return True


def _snapshot_files(snapshot: Path, cache: Path) -> list[dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    cache_resolved = cache.resolve()
    for candidate in sorted(snapshot.rglob("*")):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(cache_resolved)
        except ValueError as exc:
            raise RuntimeError("staged model escaped the approved cache") from exc
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("staged model contains a non-regular artifact")
        key = relative.as_posix()
        files[key] = {
            "path": key,
            "size_bytes": metadata.st_size,
            "sha256": _sha256(resolved),
        }
    if not files:
        raise RuntimeError("staged model snapshot contains no files")
    return [files[key] for key in sorted(files)]


def _download_direct(item: Mapping[str, object], cache: Path) -> Path:
    target = cache / str(item["path"])
    if target.exists() and not target.is_symlink() and _sha256(target) == item["sha256"]:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".model-stage-", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with urllib.request.urlopen(str(item["url"]), timeout=120) as response, temporary.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(temporary) != item["sha256"]:
            raise RuntimeError(f"downloaded alignment artifact failed verification: {item['role']}")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _artifact(
    item: Mapping[str, object],
    files: Iterable[Mapping[str, object]],
    *,
    role: str | None = None,
) -> dict[str, object]:
    return {
        "role": role or item["role"],
        "model_id": item["model_id"],
        "revision": item["revision"],
        "license": item["license"],
        "files": list(files),
    }


def _write_manifest(cache: Path, artifacts: list[dict[str, object]]) -> None:
    target = cache / "approved-model-manifest.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".manifest-", dir=cache)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(
                {"schema_version": TRANSCRIPTION_SCHEMA, "artifacts": artifacts},
                output,
                indent=2,
                sort_keys=True,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[vault] transcription manifest sealed: {len(artifacts)} artifact sets")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", nargs="?")
    parser.add_argument("--catalog", type=Path, default=Path("config/models.json"))
    parser.add_argument("--model-root", type=Path, default=Path("/models"))
    parser.add_argument(
        "--groups",
        default="review,transcription-asr,transcription-alignment-en",
        help="comma-separated review and transcription module groups",
    )
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true", help="omit the Linux generator when staging review models for a native Mac generator")
    parser.add_argument(
        "--review-profile",
        choices=("portable", "quality"),
        default="portable",
    )
    args = parser.parse_args()
    groups = frozenset(value.strip() for value in args.groups.split(",") if value.strip())
    if not groups or not groups.issubset(STAGE_GROUPS):
        parser.error("--groups contains an unsupported model module")
    transcription_selected = any(
        value.startswith("transcription-") for value in groups
    )
    root = args.model_root.resolve()
    cache = root / "huggingface" / "hub"
    cache.mkdir(parents=True, exist_ok=True)
    if transcription_selected:
        # WhisperX initializes TORCH_HOME even when its packaged VAD is used.
        # Runtime mounts the model vault read-only, so create it while staging.
        (root / "torch").mkdir(parents=True, exist_ok=True)
    payload = _catalog(args.catalog)
    token = _token(args)
    try:
        from huggingface_hub import snapshot_download
        transcription_artifacts: list[dict[str, object]] = []
        dependency_index = 0
        for raw in payload.get("models", []):
            if not isinstance(raw, dict) or not _selected(
                raw, groups, review_profile=args.review_profile, retrieval_only=args.retrieval_only
            ):
                continue
            if raw.get("gated") and not token:
                raise RuntimeError(
                    f"{raw.get('model_id')} is gated; accept its terms and rerun with --token-stdin"
                )
            print(f"[vault] acquiring {raw['model_id']} @ {str(raw['revision'])[:12]}")
            snapshot_path = Path(
                snapshot_download(
                    repo_id=str(raw["model_id"]),
                    revision=str(raw["revision"]),
                    cache_dir=cache,
                    token=token,
                    local_files_only=False,
                )
            )
            if str(raw["group"]).startswith("transcription-"):
                role = str(raw["role"])
                if role == "diarization_dependency":
                    dependency_index += 1
                    role = f"diarization_dependency_{dependency_index}"
                transcription_artifacts.append(
                    _artifact(raw, _snapshot_files(snapshot_path, cache), role=role)
                )
        for raw in payload.get("direct_files", []):
            if not isinstance(raw, dict) or not _selected(
                raw, groups, review_profile=args.review_profile
            ):
                continue
            print(f"[vault] acquiring {raw['model_id']} alignment artifact")
            target = _download_direct(raw, cache)
            transcription_artifacts.append(
                _artifact(
                    raw,
                    [
                        {
                            "path": target.relative_to(cache).as_posix(),
                            "size_bytes": target.stat().st_size,
                            "sha256": _sha256(target),
                        }
                    ],
                )
            )
        if transcription_selected:
            import nltk

            nltk_root = root / "nltk_data"
            nltk_root.mkdir(parents=True, exist_ok=True)
            print("[vault] acquiring pinned-language tokenizer support: punkt_tab")
            if not nltk.download("punkt_tab", download_dir=nltk_root, quiet=True):
                raise RuntimeError("NLTK punkt_tab staging failed")
            _write_manifest(cache, transcription_artifacts)
    finally:
        token = None
    print("[vault] pinned model staging complete; no access token retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
