#!/usr/bin/env python3
"""Evaluate newly authored Pump Cedar source packets with an explicit local model.

This never downloads/starts a model. --write-corpus creates fresh reviewable
text files and a manifest without any model call. The model mode evaluates
each extracted-unit-shaped packet; it does not qualify ingestion/transcription,
the browser, hierarchy, whole-matter recall, or a model portfolio.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from case_intelligence.generation import (EvidenceItem, GenerationRejected,
    GenerationUnavailable, GroundedGenerationService, OllamaGenerator, _bounded_json_get)
from case_intelligence.workflow_quality_gold import (CRITERION, FOLLOW_UP,
    SUITE, UNSUPPORTED_QUESTION, USEFULNESS_RUBRIC, classification_metrics,
    fingerprint, sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-corpus", type=Path)
    parser.add_argument("--endpoint")
    parser.add_argument("--model")
    parser.add_argument("--expected-digest")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = sources()
    if args.write_corpus:
        if any((args.endpoint, args.model, args.expected_digest, args.output)):
            parser.error("Choose corpus creation or model evaluation, not both.")
        args.write_corpus.mkdir(parents=True, exist_ok=False)
        for case in cases:
            directory = args.write_corpus / case.case_id
            directory.mkdir()
            for number, text in enumerate(case.units, 1):
                (directory / f"unit-{number:03d}.txt").write_text(text + "\n", encoding="utf-8")
        (args.write_corpus / "manifest.json").write_text(json.dumps({"suite": SUITE,
            "synthetic": True, "fingerprint": fingerprint(), "criterion": CRITERION,
            "sources": [asdict(case) for case in cases], "usefulness_rubric": USEFULNESS_RUBRIC}, indent=2) + "\n")
        print(f"Created {len(cases)} authored source cases; no model evaluation performed.")
        return
    if not all((args.endpoint, args.model, args.expected_digest, args.output)):
        parser.error("Model evaluation requires --endpoint, --model, --expected-digest and --output.")
    parsed = urlparse(args.endpoint)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username
        or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        parser.error("Use an explicit HTTP 127.0.0.1 endpoint.")
    if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", args.expected_digest):
        parser.error("Provide the expected immutable SHA-256 artifact digest.")
    if args.output.exists():
        parser.error("Choose a new receipt path; earlier results are never overwritten.")
    expected = args.expected_digest.removeprefix("sha256:")
    tags = _bounded_json_get(args.endpoint.rstrip("/") + "/api/tags", timeout=5)
    model = next((item for item in tags.get("models", []) if item.get("name") == args.model), None)
    if not model or model.get("digest", "").removeprefix("sha256:") != expected:
        parser.error("The explicit local model is unavailable or its digest differs; no evaluation performed.")
    service = GroundedGenerationService(OllamaGenerator(args.endpoint, args.model, timeout=90))
    rows, predictions = [], {}
    for case in cases:
        outcomes = []
        for number, text in enumerate(case.units, 1):
            evidence = EvidenceItem("S1", case.title, f"Authored unit {number}", text,
                                    case.evidence_kind, case.case_id)
            try:
                decision = service.classify_source(criterion=CRITERION, include_guidance="",
                    exclude_guidance="", evidence=(evidence,), output_tokens=400)
                outcomes.append({"unit": number, **asdict(decision)})
            except (GenerationRejected, GenerationUnavailable) as exc:
                outcomes.append({"unit": number, "decision": "needs_attention", "failure_type": type(exc).__name__})
        decisions = {item["decision"] for item in outcomes}
        predictions[case.case_id] = ("include" if "include" in decisions else
            "needs_attention" if "needs_attention" in decisions else "not_identified")
        rows.append({"source": asdict(case), "packet_outcomes": outcomes,
                     "source_decision": predictions[case.case_id]})
        print(f"{case.case_id}: {predictions[case.case_id]}", flush=True)
    evidence = tuple(EvidenceItem(f"S{number}", case.title, f"Authored unit {unit}", text,
        case.evidence_kind, case.case_id) for number, (case, unit, text) in enumerate(
        [(case, unit, text) for case in cases if case.challenge == "baseline" and case.relevant
         for unit, text in enumerate(case.units, 1)], 1))
    answers = []
    history = ()
    for question in (FOLLOW_UP, UNSUPPORTED_QUESTION):
        try:
            answer = service.answer(question, evidence, history=history)
            answers.append({"question": question, "verified_answer": asdict(answer)})
            history += (("user", question), ("assistant", answer.text))
        except (GenerationRejected, GenerationUnavailable) as exc:
            answers.append({"question": question, "failure_type": type(exc).__name__})
    result = {"suite": SUITE, "synthetic": True, "public_revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "fixture_fingerprint": fingerprint(), "model": args.model, "artifact_digest": expected,
        "criterion": CRITERION, "evaluation_boundary": "Actual model with source-shaped authored packets and production grounding verifier; source labels aggregated from every unit. Not extraction, persistence, hierarchical synthesis, browser or model qualification.",
        "metrics": classification_metrics(predictions), "results": rows, "answers": answers,
        "semantic_review": {"status": "requires independent human rubric scoring", "rubric": USEFULNESS_RUBRIC}}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
