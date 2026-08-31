from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import Matter, MatterState
from .inventory import InventoryService
from .isolation import MatterAccess, MatterStateRegistry
from .jobs import JobService
from .retrieval import RetrievalIntegrityError, RetrievalService, SearchRequest, SourceUnavailable
from .sqlite_store import SQLiteStore
from .tickets import TicketStore


class Slice1SemanticValidationError(ValueError):
    pass


_CATEGORIES = {
    "inventory", "versioning", "job_ledger", "answerable", "unanswerable",
    "cross_matter", "unauthorized_scoring", "valid_citation", "invalid_citation",
    "ticket_bypass", "projection", "persistence",
}
_METRIC_ORDER = (
    "inventory_outcomes", "versioning_outcomes", "job_ledger_outcomes",
    "answerable_selected_source_correctness", "correct_no_match_outcomes",
    "successful_cross_matter_reads", "unauthorized_requests_reaching_candidate_scoring",
    "valid_exact_citations_resolved", "invalid_or_stale_citations_rejected",
    "successful_ticket_authorization_or_replay_bypasses",
    "staff_projections_containing_forbidden_fields", "sqlite_persistence_restart_outcomes",
    "exact_lane_contributions", "lexical_lane_contributions",
)
_EXPECTED_CASES = {
    "inventory-new": ("inventory", "new_inventory", "matter-alpha"),
    "inventory-unchanged": ("inventory", "unchanged_inventory", "matter-alpha"),
    "inventory-unsupported": ("inventory", "unsupported_inventory", "matter-alpha"),
    "version-changed": ("versioning", "changed_version", "matter-alpha"),
    "version-missing": ("versioning", "missing", "matter-alpha"),
    "version-reappeared": ("versioning", "reappeared", "matter-alpha"),
    "version-no-move": ("versioning", "no_move_inference", "matter-alpha"),
    "ledger-success": ("job_ledger", "derive_success", "matter-alpha"),
    "ledger-idempotent": ("job_ledger", "derive_idempotent", "matter-alpha"),
    "ledger-restart": ("job_ledger", "ledger_restart", "matter-alpha"),
    "answer-alpha-exact": ("answerable", "alpha_exact", "matter-alpha"),
    "answer-bravo-lexical": ("answerable", "bravo_lexical", "matter-bravo"),
    "no-match": ("unanswerable", "no_match", "matter-alpha"),
    "cross-search": ("cross_matter", "cross_search", "matter-alpha"),
    "cross-selection": ("cross_matter", "cross_selection", "matter-alpha"),
    "cross-candidate": ("cross_matter", "mixed_candidate", "matter-alpha"),
    "unauthorized-alpha": ("unauthorized_scoring", "unauthorized_alpha", "matter-alpha"),
    "unauthorized-bravo": ("unauthorized_scoring", "unauthorized_bravo", "matter-bravo"),
    "citation-alpha": ("valid_citation", "valid_alpha", "matter-alpha"),
    "citation-bravo": ("valid_citation", "valid_bravo", "matter-bravo"),
    "citation-tampered": ("invalid_citation", "tampered_excerpt", "matter-alpha"),
    "citation-stale": ("invalid_citation", "stale_version", "matter-alpha"),
    "ticket-wrong-actor": ("ticket_bypass", "ticket_wrong_actor", "matter-alpha"),
    "ticket-stale": ("ticket_bypass", "ticket_stale", "matter-alpha"),
    "ticket-search": ("ticket_bypass", "search_mints_ticket", "matter-alpha"),
    "projection-search": ("projection", "search_projection", "matter-alpha"),
    "projection-ticket": ("projection", "ticket_projection", "matter-alpha"),
    "persistence-catalog": ("persistence", "catalog_reopen", "matter-alpha"),
    "persistence-derived": ("persistence", "derived_reopen", "matter-alpha"),
}


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_suite(suite: dict[str, Any], fixture: dict[str, Any]) -> None:
    required = {"schema_version", "suite_id", "suite_version", "fixture_id", "fixture_path", "evaluation_time", "cases"}
    if set(suite) != required or suite["schema_version"] != "1.0" or suite["suite_id"] != "slice1a-suite":
        raise Slice1SemanticValidationError("malformed Slice 1A suite")
    if suite["fixture_id"] != fixture.get("fixture_id"):
        raise Slice1SemanticValidationError("fixture identity mismatch")
    ids = [case.get("case_id") for case in suite["cases"]]
    if len(ids) != len(set(ids)) or set(ids) != set(_EXPECTED_CASES):
        raise Slice1SemanticValidationError("suite cases are duplicated, omitted, or invented")
    for case in suite["cases"]:
        if set(case) != {"case_id", "category", "operation", "matter_id", "expected_outcome"}:
            raise Slice1SemanticValidationError("malformed case")
        if (case["category"], case["operation"], case["matter_id"]) != _EXPECTED_CASES[case["case_id"]]:
            raise Slice1SemanticValidationError("case definition tampering")
        if case["category"] not in _CATEGORIES or case["expected_outcome"] != "passed":
            raise Slice1SemanticValidationError("unsupported case expectation")
    parsed = datetime.fromisoformat(suite["evaluation_time"].replace("Z", "+00:00"))
    if not suite["evaluation_time"].endswith("Z") or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise Slice1SemanticValidationError("evaluation_time must be UTC Z")


def _environment(root: Path, fixture_root: Path):
    roots = {}
    for name in ("alpha", "bravo"):
        target = root / name
        shutil.copytree(fixture_root / f"matter-{name}" / "input", target)
        roots[name] = target
    registry = MatterStateRegistry([
        Matter(matter_id="matter-alpha", display_name="Synthetic Alpha", state=MatterState.ACTIVE),
        Matter(matter_id="matter-bravo", display_name="Synthetic Bravo", state=MatterState.ACTIVE),
    ])
    store = SQLiteStore(root / "catalog.sqlite")
    inventory = InventoryService(store, registry, clock=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc))
    for name in ("alpha", "bravo"):
        matter = f"matter-{name}"; location = f"location-{name}"
        store.register_matter(matter, f"Synthetic {name.title()}")
        inventory.register_location(matter, location, f"Synthetic {name.title()} input", roots[name], f"\\\\synthetic\\{name}")
    access = MatterAccess({"actor-alpha": {"matter-alpha"}, "actor-bravo": {"matter-bravo"}})
    tickets = TicketStore(registry=registry, clock=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc), token_source=lambda size: b"e" * size)
    return store, registry, inventory, access, roots, tickets


def _derive(store, registry, inventory, matter: str, location: str, key: str):
    outcome = inventory.inventory(matter, location, key)
    job = JobService(store, registry, clock=lambda: datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc))
    while job.run_next(matter):
        pass
    return outcome


def _forbidden(value: Any, *, key: str = "") -> bool:
    forbidden_keys = {"relative_path", "synthetic_root", "canonical_unc_root", "sha256", "rrf_score", "score", "lane", "processor_version", "traceback", "token"}
    if key.casefold() in forbidden_keys:
        return True
    if isinstance(value, dict):
        return any(_forbidden(v, key=str(k)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_forbidden(v) for v in value)
    if isinstance(value, str):
        folded = value.casefold()
        return "/tmp/" in folded or "\\\\synthetic\\" in folded or "synthetic_root" in folded
    return False


def _execute(case: dict[str, Any], fixture_root: Path) -> tuple[str, dict[str, int]]:
    contributions = {"exact": 0, "lexical": 0}
    with tempfile.TemporaryDirectory(prefix="case-intelligence-slice1a-") as directory:
        store, registry, inventory, access, roots, tickets = _environment(Path(directory), fixture_root)
        op = case["operation"]
        matter = case["matter_id"]
        name = matter.removeprefix("matter-")
        location = f"location-{name}"
        try:
            if op == "new_inventory":
                passed = inventory.inventory(matter, location, "one").new == 3
            elif op == "unchanged_inventory":
                inventory.inventory(matter, location, "one")
                passed = inventory.inventory(matter, location, "two").unchanged == 3
            elif op == "unsupported_inventory":
                inventory.inventory(matter, location, "one")
                passed = store.connection.execute("SELECT count(*) FROM job WHERE matter_id=? AND state='not_processed'", (matter,)).fetchone()[0] == 2
            elif op in {"changed_version", "missing", "reappeared", "no_move_inference"}:
                inventory.inventory(matter, location, "one")
                report = roots[name] / "nested/report.txt"; original = report.read_bytes()
                if op == "changed_version":
                    report.write_bytes(original + b"changed\n")
                    passed = inventory.inventory(matter, location, "two").changed == 1
                elif op == "missing":
                    report.unlink(); passed = inventory.inventory(matter, location, "two").missing == 1
                elif op == "reappeared":
                    report.unlink(); inventory.inventory(matter, location, "two"); report.write_bytes(original)
                    passed = inventory.inventory(matter, location, "three").reappeared == 1
                else:
                    report.rename(roots[name] / "renamed.txt")
                    result = inventory.inventory(matter, location, "two")
                    passed = result.new == 1 and result.missing == 1
            elif op in {"derive_success", "derive_idempotent", "ledger_restart"}:
                _derive(store, registry, inventory, matter, location, "one")
                before = store.connection.execute("SELECT count(*) FROM segment WHERE matter_id=?", (matter,)).fetchone()[0]
                if op == "ledger_restart":
                    path = store.path; store.close(); store = SQLiteStore(path)
                passed = before == 1 and store.connection.execute("SELECT count(*) FROM segment WHERE matter_id=?", (matter,)).fetchone()[0] == 1
            else:
                for side in ("alpha", "bravo"):
                    _derive(store, registry, inventory, f"matter-{side}", f"location-{side}", f"scan-{side}")
                service = RetrievalService(store, registry, access, tickets)
                actor = f"actor-{name}"
                query = "CITRINE-FALCON-731" if op in {"alpha_exact", "valid_alpha"} else "shared red bicycle"
                if op in {"alpha_exact", "bravo_lexical", "valid_alpha", "valid_bravo"}:
                    response = service.search(actor, SearchRequest(case["case_id"], matter, query))
                    passed = response.outcome == "matched" and response.results[0].source_name == "report.txt"
                    if op == "alpha_exact":
                        contributions["exact"] = int(passed)
                    elif op == "bravo_lexical":
                        contributions["lexical"] = int(passed)
                elif op == "no_match":
                    passed = service.search(actor, SearchRequest("none", matter, "words not present")).outcome == "no_match"
                elif op in {"cross_search", "unauthorized_alpha", "unauthorized_bravo"}:
                    wrong = "actor-bravo" if matter == "matter-alpha" else "actor-alpha"
                    try: service.search(wrong, SearchRequest("denied", matter, "shared red bicycle")); passed = False
                    except PermissionError: passed = service.scoring_count == 0
                elif op == "mixed_candidate":
                    base = tuple(service._current(matter))[0]
                    mixed = RetrievalService(store, registry, access, tickets, candidate_provider=lambda _: (base, replace(base, matter_id="matter-bravo" if matter == "matter-alpha" else "matter-alpha")))
                    try: mixed.search(actor, SearchRequest("mixed", matter, "shared red bicycle")); passed = False
                    except PermissionError: passed = True
                elif op == "cross_selection":
                    foreign = service.search("actor-bravo", SearchRequest("foreign", "matter-bravo", "shared red bicycle")).results[0]
                    try: service.mint_open_source(actor, matter, foreign.segment_navigation_id); passed = False
                    except PermissionError: passed = True
                elif op == "tampered_excerpt":
                    store.connection.execute("UPDATE segment SET text=text||'tamper' WHERE matter_id=?", (matter,))
                    try: service.search(actor, SearchRequest("tamper", matter, "shared red bicycle")); passed = False
                    except RetrievalIntegrityError: passed = True
                elif op == "stale_version":
                    result = service.search(actor, SearchRequest("stale", matter, "shared red bicycle")).results[0]
                    (roots[name] / "nested/report.txt").write_bytes(b"new version")
                    inventory.inventory(matter, location, "changed")
                    try: service.mint_open_source(actor, matter, result.segment_navigation_id); passed = False
                    except SourceUnavailable: passed = True
                elif op == "ticket_wrong_actor":
                    result = service.search(actor, SearchRequest("ticket", matter, "shared red bicycle")).results[0]
                    try: service.mint_open_source("actor-bravo", matter, result.segment_navigation_id); passed = False
                    except PermissionError: passed = len(tickets.records) == 0
                elif op == "ticket_stale":
                    result = service.search(actor, SearchRequest("ticket", matter, "shared red bicycle")).results[0]
                    (roots[name] / "nested/report.txt").unlink()
                    try: service.mint_open_source(actor, matter, result.segment_navigation_id); passed = False
                    except SourceUnavailable: passed = len(tickets.records) == 0
                elif op == "search_mints_ticket":
                    service.search(actor, SearchRequest("search-only", matter, "shared red bicycle")); passed = len(tickets.records) == 0
                elif op == "search_projection":
                    passed = not _forbidden(asdict(service.search(actor, SearchRequest("projection", matter, "shared red bicycle"))))
                elif op == "ticket_projection":
                    result = service.search(actor, SearchRequest("projection", matter, "shared red bicycle")).results[0]
                    passed = not _forbidden(service.mint_open_source(actor, matter, result.segment_navigation_id).model_dump())
                elif op in {"catalog_reopen", "derived_reopen"}:
                    before = store.connection.execute("SELECT count(*) FROM source_version").fetchone()[0]
                    path = store.path; store.close(); store = SQLiteStore(path)
                    passed = before == store.connection.execute("SELECT count(*) FROM source_version").fetchone()[0]
                    if op == "derived_reopen": passed = passed and store.connection.execute("SELECT count(*) FROM segment").fetchone()[0] == 2
                else:
                    raise Slice1SemanticValidationError(f"unsupported operation {op}")
            return ("passed" if passed else "failed"), contributions
        finally:
            store.close()


def _metric(metric_id: str, numerator: int, denominator: int, *, zero_required: bool = False) -> dict[str, Any]:
    return {"metric_id": metric_id, "numerator": numerator, "denominator": denominator,
        "passed": numerator == 0 if zero_required else numerator == denominator}


def run_slice1_benchmark(suite: dict[str, Any], fixture: dict[str, Any], fixture_root: Path) -> dict[str, Any]:
    validate_suite(suite, fixture)
    records = []
    lane = {"exact": 0, "lexical": 0}
    for definition in suite["cases"]:
        observed, contribution = _execute(definition, fixture_root)
        lane["exact"] += contribution["exact"]; lane["lexical"] += contribution["lexical"]
        records.append({"case_id": definition["case_id"], "category": definition["category"],
            "operation": definition["operation"], "matter_id": definition["matter_id"],
            "expected_outcome": definition["expected_outcome"], "observed_outcome": observed,
            "passed": observed == definition["expected_outcome"]})
    grouped = {category: [r for r in records if r["category"] == category] for category in _CATEGORIES}
    passed_count = lambda category: sum(r["passed"] for r in grouped[category])
    metrics = [
        _metric("inventory_outcomes", passed_count("inventory"), len(grouped["inventory"])),
        _metric("versioning_outcomes", passed_count("versioning"), len(grouped["versioning"])),
        _metric("job_ledger_outcomes", passed_count("job_ledger"), len(grouped["job_ledger"])),
        _metric("answerable_selected_source_correctness", passed_count("answerable"), len(grouped["answerable"])),
        _metric("correct_no_match_outcomes", passed_count("unanswerable"), len(grouped["unanswerable"])),
        _metric("successful_cross_matter_reads", len(grouped["cross_matter"]) - passed_count("cross_matter"), len(grouped["cross_matter"]), zero_required=True),
        _metric("unauthorized_requests_reaching_candidate_scoring", len(grouped["unauthorized_scoring"]) - passed_count("unauthorized_scoring"), len(grouped["unauthorized_scoring"]), zero_required=True),
        _metric("valid_exact_citations_resolved", passed_count("valid_citation"), len(grouped["valid_citation"])),
        _metric("invalid_or_stale_citations_rejected", passed_count("invalid_citation"), len(grouped["invalid_citation"])),
        _metric("successful_ticket_authorization_or_replay_bypasses", len(grouped["ticket_bypass"]) - passed_count("ticket_bypass"), len(grouped["ticket_bypass"]), zero_required=True),
        _metric("staff_projections_containing_forbidden_fields", len(grouped["projection"]) - passed_count("projection"), len(grouped["projection"]), zero_required=True),
        _metric("sqlite_persistence_restart_outcomes", passed_count("persistence"), len(grouped["persistence"])),
        _metric("exact_lane_contributions", lane["exact"], 1),
        _metric("lexical_lane_contributions", lane["lexical"], 1),
    ]
    environment = {"dataset_classification": "synthetic", "confidential_data": False,
        "network_calls": 0, "model_calls": 0, "external_service_calls": 0,
        "container_calls": 0, "nas_calls": 0, "mnt_calls": 0, "production_selection": False}
    return {"schema_version": "1.0", "suite_id": suite["suite_id"], "suite_version": suite["suite_version"],
        "suite_sha256": _digest(suite), "fixture_id": suite["fixture_id"], "created_at": suite["evaluation_time"],
        "case_count": len(records), "environment": environment, "cases": records, "metrics": metrics,
        "limitations": ["SQLite is a development adapter; PostgreSQL remains the proposed production target.",
            "Measured only on committed synthetic fixtures; no generated answer or production pipeline selection."],
        "passed": all(r["passed"] for r in records) and all(m["passed"] for m in metrics)}


def validate_slice1_result(result: dict[str, Any], schema: dict[str, Any], suite: dict[str, Any], fixture: dict[str, Any], fixture_root: Path) -> dict[str, tuple[int, int]]:
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    expected = run_slice1_benchmark(suite, fixture, fixture_root)
    if json.dumps(result, sort_keys=True, ensure_ascii=False) != json.dumps(expected, sort_keys=True, ensure_ascii=False):
        raise Slice1SemanticValidationError("result differs from recomputed executable Slice 1A benchmark")
    metrics = {m["metric_id"]: (m["numerator"], m["denominator"]) for m in result["metrics"]}
    if tuple(metrics) != _METRIC_ORDER:
        raise Slice1SemanticValidationError("metrics omitted, duplicated, invented, or reordered")
    return copy.deepcopy(metrics)
