#!/usr/bin/env python3
"""Stage and verify the pinned Mac generator; run only synthetic acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "https://registry.ollama.ai/v2/library/qwen3.5"
SANDBOX_POLICY = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))'


def catalog(profile: str = "4b") -> dict:
    if profile not in {"4b", "9b"}:
        raise RuntimeError("invalid Mac model profile")
    name = "mac-models.json" if profile == "4b" else "mac-models-9b.json"
    value = json.loads((REPO_ROOT / "config" / name).read_text())
    if value.get("schema_version") != 1 or value.get("model") != f"qwen3.5:{profile}":
        raise RuntimeError("invalid Mac model catalog")
    return value


def digest(path: Path) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as error:
        raise RuntimeError("model artifact is missing or is not a regular file") from error
    result = hashlib.sha256()
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise RuntimeError("model artifact is missing or is not a regular file")
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return "sha256:" + result.hexdigest()


def vault_path(root: Path, *parts: str) -> Path:
    """Reject symlinked directories as well as final artifacts inside the vault."""
    if root.is_symlink():
        raise RuntimeError("model vault must not contain symlinks")
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RuntimeError("model vault must not contain symlinks")
    return candidate


def blob_path(root: Path, value: str) -> Path:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise RuntimeError("invalid artifact digest")
    return vault_path(root, "blobs", value.replace(":", "-"))


def manifest_path(root: Path, model: str = "qwen3.5:4b") -> Path:
    if model not in {"qwen3.5:4b", "qwen3.5:9b"}:
        raise RuntimeError("invalid Mac model name")
    return vault_path(root, "manifests", "registry.ollama.ai", "library", "qwen3.5", model.split(":")[1])


def artifacts(value: dict) -> list[dict]:
    manifest = value["manifest"]
    return [manifest["config"], *manifest["layers"]]


def verify(root: Path, value: dict) -> None:
    if digest(manifest_path(root, value.get("model", "qwen3.5:4b"))) != value["revision"]:
        raise RuntimeError("staged manifest does not match the pinned revision")
    for item in artifacts(value):
        path = blob_path(root, item["digest"])
        if digest(path) != item["digest"] or path.stat().st_size != item["size"]:
            raise RuntimeError("staged model artifact failed size or hash verification")


def download(url: str, target: Path, expected: str, size: int) -> None:
    if target.exists():
        if digest(target) == expected and target.stat().st_size == size:
            return
        raise RuntimeError("existing artifact failed verification; inspect the dedicated vault")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".stage-", dir=target.parent)
    temporary = Path(name)
    try:
        received = 0
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(url, timeout=120) as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                received += len(block)
                if received > size:
                    raise RuntimeError("model download exceeded pinned size")
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if received != size or digest(temporary) != expected:
            raise RuntimeError("download failed pinned size or hash verification")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def stage(root: Path, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    needed = sum(item["size"] for item in artifacts(value) if not blob_path(root, item["digest"]).exists())
    if shutil.disk_usage(root).free < needed + 5 * 1024**3:
        raise RuntimeError("model staging requires uncached artifact bytes plus 5 GiB free reserve")
    with urllib.request.urlopen(value["source"], timeout=30) as response:
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576 or "sha256:" + hashlib.sha256(raw).hexdigest() != value["revision"]:
        raise RuntimeError("registry tag changed; review a new immutable revision before staging")
    for item in artifacts(value):
        print(json.dumps({"staging": item["mediaType"], "bytes": item["size"]}), flush=True)
        download(REGISTRY + "/blobs/" + item["digest"], blob_path(root, item["digest"]), item["digest"], item["size"])
    target = manifest_path(root, value["model"])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise RuntimeError("manifest must not be a symlink")
    descriptor, name = tempfile.mkstemp(prefix=".manifest-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    verify(root, value)


def serve(root: Path, value: dict, port: int) -> None:
    verify(root, value)
    executable = shutil.which("ollama")
    if sys.platform != "darwin" or not executable or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("native serving requires macOS, Ollama, and sandbox-exec")
    env = dict(os.environ)
    env.update({
        "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(root),
        "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_CONTEXT_LENGTH": "8192",
    })
    os.execve("/usr/bin/sandbox-exec", ["sandbox-exec", "-p", SANDBOX_POLICY, executable, "serve"], env)


def case_failures(case, answer) -> list[str]:
    failures = []
    rendered = answer.text.casefold()
    if answer.answerable != case.expected_answerable:
        failures.append("answerability")
    if any(not any(term.casefold() in rendered for term in group) for group in case.required_concepts):
        failures.append("missing_concept")
    if any(term.casefold() in rendered for term in case.forbidden_concepts):
        failures.append("forbidden_concept")
    if any(not set(group).intersection(answer.used_evidence_ids) for group in case.required_evidence_groups):
        failures.append("missing_citation")
    if case.require_limitation and (answer.limitation is None or not answer.limitation.evidence_ids):
        failures.append("missing_limitation")
    return failures


def evaluate(value: dict, port: int, context_tokens: int = 8192) -> dict:
    # The evaluator accepts no caller-supplied text or remote endpoint.
    from case_intelligence.generation import GroundedGenerationService, OllamaGenerator
    from case_intelligence.model_portfolio_gold import (
        MODEL_PORTFOLIO_SUITE_ID, model_portfolio_cases, model_portfolio_fingerprint,
    )
    endpoint = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(endpoint + "/api/version", timeout=5) as response:
        runtime_version = json.loads(response.read(65_536)).get("version", "unknown")
    with urllib.request.urlopen(endpoint + "/api/tags", timeout=5) as response:
        inventory = json.loads(response.read(1_048_576))
    if not any(item.get("name") == value["model"] and item.get("digest") in (value["revision"], value["revision"].removeprefix("sha256:")) for item in inventory.get("models", [])):
        raise RuntimeError("served model does not match the pinned revision")
    service = GroundedGenerationService(OllamaGenerator(endpoint, value["model"], timeout=300, disable_thinking=True, context_tokens=context_tokens, max_output_tokens=1200, max_review_tokens=400))
    results = []
    for case in model_portfolio_cases():
        started = time.monotonic()
        failures = []
        try:
            answer = service.answer(case.question, case.evidence)
            failures = case_failures(case, answer)
        except Exception as error:
            failures.append(type(error).__name__)
        result = {"case_id": case.case_id, "passed": not failures, "failures": failures, "elapsed_ms": round((time.monotonic() - started) * 1000)}
        results.append(result)
        print(json.dumps(result), flush=True)
    return {
        "suite_id": MODEL_PORTFOLIO_SUITE_ID, "fingerprint": model_portfolio_fingerprint(),
        "model": value["model"], "revision": value["revision"], "cases": results,
        "runtime": f"Ollama {runtime_version}", "context_tokens": context_tokens,
        "passed": all(item["passed"] for item in results),
        "scope": "Synthetic generator and verifier only; retrieval, ingestion, concurrency, and real-world quality are not evaluated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "check", "serve", "evaluate"))
    parser.add_argument("--model-root", type=Path, required=True, help="Dedicated Ollama model vault outside the repository")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--profile", choices=("4b", "9b"), default="4b")
    parser.add_argument("--context", type=int, default=8192, help="Ollama evaluation context token budget")
    parser.add_argument("--output", type=Path, help="Write synthetic evaluation JSON to this file")
    args = parser.parse_args()
    root = args.model_root.expanduser().resolve()
    if root == Path(root.anchor) or root == Path.home() or root == REPO_ROOT or REPO_ROOT in root.parents:
        parser.error("use a dedicated model vault outside the repository")
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    try:
        value = catalog(args.profile)
        if args.action == "stage":
            stage(root, value)
        elif args.action == "serve":
            serve(root, value, args.port)
        else:
            verify(root, value)
        if args.action == "evaluate":
            result = evaluate(value, args.port, args.context)
            if args.output:
                args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            print(json.dumps(result, sort_keys=True))
            return 0 if result["passed"] else 1
        print(json.dumps({"status": "verified", "model": value["model"], "revision": value["revision"]}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": type(error).__name__, "detail": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
