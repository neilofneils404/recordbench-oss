#!/usr/bin/env python3
"""Run frozen R1b verifier probes, capture a local model, or score bound human grades."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from case_intelligence import claim_evaluation as evaluation
from case_intelligence.generation import (
    OllamaGenerator, OpenAICompatibleGenerator, _bounded_json_get,
)


class IdentityError(RuntimeError):
    """Fatal attribution failure: no quality receipt may be written."""


class EvaluationBoundaryError(RuntimeError):
    """Fatal transport boundary failure, never an ordinary model failure."""


class NoEvaluationRedirects(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        # Reject every 3xx before urllib can dispatch to a redirect handler,
        # including nonstandard or missing-Location responses.
        if 300 <= response.code < 400:
            response.close()
            raise EvaluationBoundaryError("Evaluation endpoint redirected; capture aborted.")
        return super().http_response(request, response)

    https_response = http_response


def evaluation_opener():
    # A local endpoint must stay local regardless of redirects or inherited
    # HTTP_PROXY/HTTPS_PROXY settings. Never alter the global urllib opener.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoEvaluationRedirects())


def local_client(backend, endpoint, model, artifact_digest):
    parsed = urlparse(endpoint)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username
        or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Use an explicit HTTP 127.0.0.1 endpoint on an authorized isolated target.")
    opener = evaluation_opener()
    client = (OllamaGenerator(endpoint, model, timeout=90, opener=opener) if backend == "ollama" else
              OpenAICompatibleGenerator(endpoint, model, timeout=90, disable_thinking=True, opener=opener))

    def check():
        try:
            if backend == "ollama":
                payload = _bounded_json_get(f"{client.endpoint}/api/tags", timeout=5, opener=opener)
                matches = [item for item in payload.get("models", []) if item.get("name") == model]
                valid = (len(matches) == 1
                         and str(matches[0].get("digest", "")).removeprefix("sha256:") == artifact_digest)
            else:
                payload = _bounded_json_get(f"{client.endpoint}/v1/models", timeout=5, opener=opener)
                matches = [item for item in payload.get("data", []) if item.get("id") == model]
                valid = len(matches) == 1
        except EvaluationBoundaryError:
            raise
        except Exception:
            raise IdentityError("Runtime identity check unavailable; capture aborted.") from None
        if not valid:
            raise IdentityError("Runtime model identity mismatch; capture aborted.")
        return {"method": "ollama_tag_digest_snapshots" if backend == "ollama" else "api_model_id_snapshots",
                "model": model, "artifact_sha256": artifact_digest if backend == "ollama" else None}

    return client, check


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probes = commands.add_parser("probes", help="No model or network calls")
    probes.add_argument("--output", type=Path, required=True)
    live = commands.add_parser("capture", help="Explicit authorized local generator; fixed evidence")
    live.add_argument("--backend", choices=("ollama", "openai"), required=True)
    live.add_argument("--endpoint", required=True)
    live.add_argument("--profile", choices=("portable", "quality"), required=True)
    live.add_argument("--model", required=True)
    live.add_argument("--runtime-profile", type=Path, required=True)
    live.add_argument("--repetitions", type=int, required=True)
    live.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("grade-template")
    template.add_argument("--capture", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--capture", type=Path, required=True)
    score.add_argument("--grades", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Choose a new output path; earlier evidence is never overwritten.")
    if args.command == "probes":
        result = evaluation.run_probes()
    elif args.command == "capture":
        runtime = json.loads(args.runtime_profile.read_text())
        evaluation.validate_runtime(runtime)
        client, check = local_client(args.backend, args.endpoint, args.model, runtime["model_artifact_sha256"])
        result = evaluation.capture(client, profile=args.profile, runtime=runtime,
                                    repetitions=args.repetitions, identity_check=check)
    else:
        receipt = json.loads(args.capture.read_text())
        result = (evaluation.grade_template(receipt) if args.command == "grade-template" else
                  evaluation.score_capture(receipt, json.loads(args.grades.read_text())))
    evaluation.write_new(args.output, result)
    print(json.dumps({"mode": result.get("mode", args.command),
                      "receipt_sha256": result.get("receipt_sha256"),
                      "release_acceptance": result.get("release_acceptance", "not_evaluated")}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, IdentityError, EvaluationBoundaryError) as exc:
        raise SystemExit(str(exc)) from None
