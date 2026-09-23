"""Frozen synthetic R1b probes and separately graded, single-pass model captures.

These are evaluation artifacts, never application state or release acceptance.
Use production verification code; do not use its verdict as semantic ground truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import time

from jsonschema import Draft202012Validator

from .generation import (
    ANSWER_SCHEMA, EvidenceItem, GenerationRejected, GenerationUnavailable,
    GroundedGenerationService, _exact_original_span, _prompt, verify_original_claim,
)

ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = ROOT / "benchmarks/r1b-claims-v1.json"
# Changing v1 requires a new version, not an updated expected fingerprint.
SUITE_SHA256 = "ec9ac26e0d8874d7f37ae5ebfa41e57bfa0072fc8488aac62af3c7bcc3211809"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def load_suite():
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    if digest(suite) != SUITE_SHA256:
        raise ValueError("Frozen challenge set or rubric changed; use a new suite version.")
    return suite


def seal(receipt):
    return {**receipt, "receipt_sha256": digest(receipt)}


def validate_receipt(receipt):
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != digest(body):
        raise ValueError("Capture digest mismatch.")
    if receipt.get("suite_sha256") != SUITE_SHA256:
        raise ValueError("Capture uses a different frozen suite.")
    if receipt.get("schema_version") != 1:
        raise ValueError("Unsupported receipt schema.")
    if receipt.get("mode") == "model_capture":
        repetitions = receipt.get("configuration", {}).get("repetitions")
        if type(repetitions) is not int or not 1 <= repetitions <= 20:
            raise ValueError("Capture repetitions invalid.")
        cases = {case["case_id"]: case for case in load_suite()["cases"]}
        expected = {f"{case_id}:{repetition}" for case_id in cases
                    for repetition in range(1, repetitions + 1)}
        rows = receipt.get("results", [])
        if (len(rows) != len(expected) or {row["sample_id"] for row in rows} != expected
            or receipt.get("generation", {}).get("attempts") != len(expected)):
            raise ValueError("Capture must contain every planned sample exactly once.")
        for row in rows:
            if (row.get("case_id") not in cases or type(row.get("repetition")) is not int
                or row["sample_id"] != f"{row['case_id']}:{row['repetition']}"
                or row.get("state") not in {"generated", "generation_failure"}):
                raise ValueError("Invalid capture sample identity or state.")
        # Verification is code-sensitive. Score with the recorded implementation;
        # do not silently replay a later verifier against an old capture.
        fingerprints = receipt["execution"]["implementation_sha256"]
        if set(fingerprints) != {"src/case_intelligence/generation.py",
                                "src/case_intelligence/claim_evaluation.py", "scripts/evaluate-claims.py"}:
            raise ValueError("Incomplete implementation fingerprints.")
        for name, recorded in fingerprints.items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != recorded:
                raise ValueError("Score with the captured implementation; code fingerprint changed.")
        for row in rows:
            if row["state"] == "generated":
                evidence = tuple(EvidenceItem(**item) for item in cases[row["case_id"]]["evidence"])
                if row["verification"] != verify_output(row["raw"], evidence):
                    raise ValueError("Stored verification differs from captured code replay.")
                if row["schema_valid"] is not Draft202012Validator(ANSWER_SCHEMA).is_valid(row["raw"]):
                    raise ValueError("Stored schema validity differs from captured output.")
        if receipt["generation"] != generation_counts(rows):
            raise ValueError("Generation counters disagree with the complete capture.")


def model_records(profile, *, generator_exercised):
    manifest = json.loads((ROOT / "config/models.json").read_text())
    records = []
    for role in ("generator", "embedding", "reranker"):
        entry = next(item for item in manifest["models"] if item["role"] == role
                     and (role != "generator" or item["profile"] == profile))
        records.append({**entry, "execution": "operator_declared_generator_capture" if role == "generator"
                        and generator_exercised else "not_exercised",
                        "revision_basis": "repository_manifest_not_runtime_attestation"})
    return {"manifest_sha256": digest(manifest), "components": records}


def execution_metadata():
    # Deliberately omit hostname, username, endpoint, environment and filesystem paths.
    return {
        "os": platform.system(), "os_release": platform.release(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT)),
        "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("src/case_intelligence/generation.py",
                         "src/case_intelligence/claim_evaluation.py",
                         "scripts/evaluate-claims.py")},
    }


def base_receipt(mode, profile):
    suite = load_suite()
    return {
        "schema_version": 1, "suite_id": suite["suite_id"], "suite_sha256": SUITE_SHA256,
        "mode": mode, "synthetic": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution": execution_metadata(),
        "models": model_records(profile, generator_exercised=mode == "model_capture"),
        "release_acceptance": "pending_no_release_threshold_defined",
        "supported_hardware_acceptance": "not_established",
        "retrieval": "fixed_evidence_no_embedding_or_reranker_calls",
        "scope": "single_pass_claim_checks_no_repair_retrieval_storage_or_browser_acceptance",
    }


def claim_slots(raw):
    """Keep original positions and malformed slots; never count only survivors."""
    if not isinstance(raw, dict):
        return []
    rows = [(f"claim-{index}", value) for index, value in enumerate(raw["claims"])] if isinstance(raw.get("claims"), list) else []
    if raw.get("limitation") is not None:
        rows.append(("limitation", raw["limitation"]))
    return rows


def verify_output(raw, evidence):
    evidence_map = {item.evidence_id: item for item in evidence}
    rows = []
    for slot, value in claim_slots(raw):
        claim = (verify_original_claim(value.get("text"), value.get("evidence_ids"), evidence_map)
                 if isinstance(value, dict) and set(value) == {"text", "evidence_ids"} else None)
        rows.append({"slot": slot, "ordinary_accepted": claim is not None,
                     "exact_span_accepted": _exact_original_span(claim, evidence_map) is not None})
    outcomes = {}
    for path, strict in (("ordinary", False), ("exact_span", True)):
        try:
            answer = GroundedGenerationService._verify(raw, evidence, 0, strict_originals=strict)
            outcomes[path] = {"state": "answer" if answer.answerable else "abstained",
                              "retained_claims": len(answer.claims),
                              "omitted_claims": answer.omitted_claims}
        except (GenerationRejected, TypeError, AttributeError) as exc:
            outcomes[path] = {"state": "rejected", "failure_type": type(exc).__name__}
        # The application never retains a candidate from a rejected/abstained
        # response, even when that candidate alone passes the text predicate.
        if outcomes[path]["state"] != "answer":
            for row in rows:
                row[path + "_accepted"] = False
    return {"claims": rows, "response": outcomes}


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def verifier_metrics(rows):
    invalid = [row for row in rows if not (row["semantic_valid"] and row["citations_valid"])]
    valid = [row for row in rows if row["semantic_valid"] and row["citations_valid"]]
    return {path: {
        "false_acceptance": fraction(sum(row[path + "_accepted"] for row in invalid), len(invalid)),
        "false_rejection": fraction(sum(not row[path + "_accepted"] for row in valid), len(valid)),
        "semantic_false_acceptance": fraction(sum(row[path + "_accepted"] for row in rows
            if not row["semantic_valid"]), sum(not row["semantic_valid"] for row in rows)),
        "citation_false_acceptance": fraction(sum(row[path + "_accepted"] for row in rows
            if not row["citations_valid"]), sum(not row["citations_valid"] for row in rows)),
    } for path in ("ordinary", "exact_span")}


def run_probes(profile="portable"):
    receipt = base_receipt("injected_verifier_probes", profile)
    rows = []
    for case in load_suite()["cases"]:
        evidence = tuple(EvidenceItem(**item) for item in case["evidence"])
        for candidate in case["candidates"]:
            result = verify_output(candidate["output"], evidence)
            if len(result["claims"]) != 1:
                raise ValueError("Frozen probes require exactly one claim per candidate.")
            rows.append({"case_id": case["case_id"], "category": case["category"],
                         **candidate, **result["claims"][0], "response": result["response"]})
    receipt.update(results=rows, verifier=verifier_metrics(rows),
                   generation={"status": "not_measured_injected_outputs", "model_calls": 0},
                   offline_readiness={"status": "not_exercised_no_models_loaded"})
    return seal(receipt)


def validate_runtime(runtime):
    required = {"runtime_name", "runtime_version", "accelerator", "accelerator_memory_gib",
                "driver", "model_artifact_sha256", "offline_readiness", "offline_evidence_sha256",
                "upstream_model_id", "upstream_revision", "license"}
    if not isinstance(runtime, dict) or set(runtime) != required:
        raise ValueError("Runtime profile must contain exactly the documented fields.")
    for field in ("runtime_name", "runtime_version", "accelerator", "driver"):
        if not isinstance(runtime[field], str) or not 1 <= len(runtime[field]) <= 160:
            raise ValueError("Runtime description is missing or too long.")
    memory = runtime["accelerator_memory_gib"]
    if type(memory) not in (int, float) or not 0 <= memory <= 100_000:
        raise ValueError("Record actual accelerator memory (0 for CPU).")
    if not re.fullmatch(r"[0-9a-f]{64}", str(runtime["model_artifact_sha256"])):
        raise ValueError("Record the immutable loaded artifact SHA-256.")
    if runtime["offline_readiness"] not in {"not_exercised", "operator_attested"}:
        raise ValueError("Offline readiness must be not_exercised or operator_attested.")
    evidence = runtime["offline_evidence_sha256"]
    if ((runtime["offline_readiness"] == "not_exercised" and evidence is not None)
        or (runtime["offline_readiness"] == "operator_attested"
            and not re.fullmatch(r"[0-9a-f]{64}", str(evidence)))):
        raise ValueError("Offline attestation requires a separate evidence digest.")


def capture(client, *, profile, runtime, repetitions, identity_check):
    """Call a real production adapter once per packet; don't hide repair drafts.

    identity_check is fatal on mismatch. Runtime artifact/offline declarations
    are operator evidence, not a claim that an API model name attests weights.
    """
    validate_runtime(runtime)
    generator = model_records(profile, generator_exercised=False)["components"][0]
    if any(runtime[key] != generator[field] for key, field in (
        ("upstream_model_id", "model_id"), ("upstream_revision", "revision"), ("license", "license"))):
        raise ValueError("Declared artifact provenance must match the selected pinned model profile.")
    if type(repetitions) is not int or not 1 <= repetitions <= 20:
        raise ValueError("Choose 1 to 20 repetitions before running the model.")
    receipt = base_receipt("model_capture", profile)
    receipt.update(runtime={**runtime, "basis": "operator_declared_not_independently_verified"},
                   configuration={"repetitions": repetitions, "seed": None,
                       "seed_status": "production_adapters_do_not_set_seed",
                       "history": [], "working_context": "", "grounding_repair": False,
                       "adapter": type(client).__name__, "model": client.model,
                       "disable_thinking": getattr(client, "disable_thinking", None),
                       "temperature": 0.1, "output_tokens": 1200,
                       "context_tokens": 8192 if type(client).__name__ == "OllamaGenerator" else "server_configured",
                       "response_schema": ANSWER_SCHEMA}, results=[])
    for case in load_suite()["cases"]:
        evidence = tuple(EvidenceItem(**item) for item in case["evidence"])
        system, user = _prompt(case["question"], evidence, (), "", grounding_repair=False)
        for repetition in range(1, repetitions + 1):
            row = {"sample_id": f"{case['case_id']}:{repetition}", "case_id": case["case_id"],
                   "repetition": repetition, "prompt": {"system": system, "user": user}}
            identity_check()
            start = time.monotonic()
            try:
                raw = client.generate(question=case["question"], evidence=evidence)
                row.update(state="generated", raw=raw, verification=verify_output(raw, evidence),
                           schema_valid=Draft202012Validator(ANSWER_SCHEMA).is_valid(raw))
            except (GenerationRejected, GenerationUnavailable) as exc:
                # No remote error text: it may contain endpoint or runtime details.
                row.update(state="generation_failure", failure_type=type(exc).__name__)
            finally:
                identity_check()
            row["elapsed_ms"] = round((time.monotonic() - start) * 1000)
            receipt["results"].append(row)
    identity_check()
    receipt["generation"] = generation_counts(receipt["results"])
    return seal(receipt)


def generation_counts(rows):
    return {"status": "requires_independent_human_grading",
        "attempts": len(rows),
        "generated": sum(row["state"] == "generated" for row in rows),
        "schema_invalid": sum(not row["schema_valid"] for row in rows if row["state"] == "generated"),
        "abstained": sum(isinstance(row.get("raw"), dict) and row["raw"].get("answerable") is False
                         for row in rows),
    }


def grade_template(receipt):
    validate_receipt(receipt)
    if receipt["mode"] != "model_capture":
        raise ValueError("Only real-model captures receive human generation grades.")
    return {"capture_sha256": receipt["receipt_sha256"], "rubric_sha256": SUITE_SHA256,
            "grader_id": "", "samples": [{
                "sample_id": row["sample_id"], "answer_correct": None, "rationale": "",
                "claims": [{"slot": slot, "semantic_valid": None, "citations_valid": None,
                            "rationale": ""} for slot, _ in claim_slots(row["raw"])],
            } for row in receipt["results"] if row["state"] == "generated"]}


def score_capture(receipt, grades):
    template = grade_template(receipt)
    if (grades.get("capture_sha256") != template["capture_sha256"]
        or grades.get("rubric_sha256") != SUITE_SHA256):
        raise ValueError("Grades are not bound to this capture and rubric.")
    if not isinstance(grades.get("grader_id"), str) or not grades["grader_id"].strip():
        raise ValueError("Use a pseudonymous grader ID, not a personal identity.")
    expected = {row["sample_id"]: row for row in template["samples"]}
    samples = grades.get("samples", [])
    if len(samples) != len(expected) or {row["sample_id"] for row in samples} != set(expected):
        raise ValueError("Grade every generated sample exactly once.")
    by_id = {row["sample_id"]: row for row in receipt["results"]}
    rows = []
    for sample in samples:
        if type(sample.get("answer_correct")) is not bool or not sample.get("rationale", "").strip():
            raise ValueError("Complete answer correctness and rationale for every sample.")
        slots = [row["slot"] for row in expected[sample["sample_id"]]["claims"]]
        claims = sample.get("claims", [])
        if len(claims) != len(slots) or {row["slot"] for row in claims} != set(slots):
            raise ValueError("Grade every raw claim and limitation exactly once.")
        verdicts = {row["slot"]: row for row in by_id[sample["sample_id"]]["verification"]["claims"]}
        for claim in claims:
            if (any(type(claim.get(field)) is not bool for field in ("semantic_valid", "citations_valid"))
                or not claim.get("rationale", "").strip()):
                raise ValueError("Complete independent semantic and citation grades with rationales.")
            rows.append({**claim, **verdicts[claim["slot"]], "sample_id": sample["sample_id"]})
        raw_row = by_id[sample["sample_id"]]
        if sample["answer_correct"] and (not raw_row["schema_valid"]
            or not isinstance(raw_row["raw"], dict) or raw_row["raw"].get("answerable") is not True
            or not raw_row["raw"].get("claims")
            or any(not (claim["semantic_valid"] and claim["citations_valid"]) for claim in claims)):
            raise ValueError("Correct answers must be well-formed, answerable and have only valid claims.")
    attempted = len(receipt["results"])
    failures = attempted - len(samples)
    errors = sum(not row["answer_correct"] for row in samples)
    return seal({"schema_version": 1, "suite_sha256": SUITE_SHA256,
        "capture_sha256": receipt["receipt_sha256"], "grades_sha256": digest(grades),
        "generation": {
            "failed_attempts": fraction(failures, attempted),
            "answer_error_among_generated": fraction(errors, len(samples)),
            "unsuccessful_attempts": fraction(errors + failures, attempted),
            "semantic_claim_errors": fraction(sum(not row["semantic_valid"] for row in rows), len(rows)),
            "citation_claim_errors": fraction(sum(not row["citations_valid"] for row in rows), len(rows)),
        }, "verifier": verifier_metrics(rows), "grades": grades, "claim_results": rows,
        "release_acceptance": "pending_no_release_threshold_defined",
        "limitation": "Human-graded fixed synthetic packets; not production error rates or installed-stack acceptance."})


def write_new(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
