"""Stream a full-text synthesis basis inside an explicit workspace snapshot.

Reads own one short read transaction. ``validate_locked`` is deliberately a
locked operation: the application owns the source guard and write transaction
that also saves the job. No independent writer or model call lives here.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from .full_text_review import read_locator
from .hierarchical_synthesis import POLICY, digest
from .workspace_store import WorkspaceProblem


VERSION = 1
ADMISSION = {"version": VERSION, "findings": POLICY["max_groups"] * 4,
             "original_characters": POLICY["characters_per_source"],
             "input_bytes": 1_000_000, "receipt_bytes": 400_000,
             "sources": 1_000, "ranges": 20_000}


def encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def criterion_question(criterion):
    """Preserve the complete saved criterion under the existing question limit."""
    fields = (("Instructions", criterion["instructions"]),
              ("Include guidance", criterion["include_guidance"]),
              ("Exclude guidance", criterion["exclude_guidance"]))
    if any(not isinstance(value, str) for _, value in fields) or not fields[0][1].strip():
        raise WorkspaceProblem("The selected review criterion has invalid instructions or guidance.")
    question = ("\n\n".join(f"{label}:\n{value}" for label, value in fields if value.strip())
                if any(value.strip() for _, value in fields[1:]) else fields[0][1])
    if len(question) > 2_000:
        raise WorkspaceProblem("The complete review criterion exceeds the 2,000-character synthesis question limit. Its instructions or guidance cannot be truncated.")
    return question


def _hash_row(hasher, value):
    # Length-delimited canonical rows cannot alias adjacent row boundaries.
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    hasher.update(str(len(raw)).encode() + b":" + raw)


class FullTextSynthesisRepository:
    def __init__(self, *, connection, lock, authorize):
        self.connection, self.lock, self.authorize = connection, lock, authorize

    def capture(self, matter_id, actor_id, run_id):
        """Read all metadata consistently, retaining at most 48 rationales."""
        with self.lock, self.connection:
            if self.connection.in_transaction:
                raise RuntimeError("Full-text admission capture requires its own read transaction.")
            self.connection.execute("BEGIN")
            self.authorize(matter_id, actor_id)
            return self._capture_locked(matter_id, run_id, candidates=True)

    def validate_locked(self, matter_id, actor_id, receipt, *, historical=False):
        """The caller must include this check in its guarded job transaction.

        Historical output keeps its frozen decision context, even after human
        edits or deletion of the original review. Original source identities and
        the selected source-set membership are still checked on every read.
        """
        if not self.connection.in_transaction:
            raise RuntimeError("Full-text validation requires the caller's transaction.")
        self.authorize(matter_id, actor_id)
        if receipt.get("version") != VERSION or receipt.get("matter_id") != matter_id:
            raise WorkspaceProblem("This full-text synthesis belongs to an incompatible matter or format.")
        self._validate_sources_locked(matter_id, receipt)
        if not historical:
            current = self._capture_locked(matter_id, receipt["run_id"], candidates=False)["receipt"]
            if current["snapshot_digest"] != receipt.get("snapshot_digest"):
                raise WorkspaceProblem("The selected full-text review or a human decision changed. Start a new synthesis from the terminal review.")

    def validate_source_scope_locked(self, receipt):
        """Caller authorizes the actual reader; reuse or own one read snapshot."""
        with self.lock:
            if receipt.get("version") != VERSION:
                raise WorkspaceProblem("Unknown full-text synthesis input version.")
            if self.connection.in_transaction:
                self._validate_sources_locked(receipt["matter_id"], receipt)
            else:
                with self.connection:
                    self.connection.execute("BEGIN")
                    self._validate_sources_locked(receipt["matter_id"], receipt)

    def _scope_digest(self, matter_id, source_set_id):
        if not source_set_id:
            return None
        if self.connection.execute("SELECT 1 FROM workbench_source_set WHERE matter_id=? AND source_set_id=?",
                                   (matter_id, source_set_id)).fetchone() is None:
            raise WorkspaceProblem("The selected full-text source set is no longer available.")
        hasher = hashlib.sha256()
        for row in self.connection.execute("SELECT document_id FROM workbench_source_set_item WHERE matter_id=? AND source_set_id=? ORDER BY document_id",
                                           (matter_id, source_set_id)):
            _hash_row(hasher, row[0])
        return hasher.hexdigest()

    def _validate_sources_locked(self, matter_id, receipt):
        if self._scope_digest(matter_id, receipt.get("source_set_id")) != receipt.get("source_set_digest"):
            raise WorkspaceProblem("The selected source set changed after the full-text synthesis input was frozen.")
        sources = receipt.get("sources")
        if not isinstance(sources, list) or not sources or len(sources) > ADMISSION["sources"]:
            raise WorkspaceProblem("The frozen full-text source population is invalid.")
        for source in sources:
            row = self.connection.execute("SELECT version_id,content_basis_digest,source_state FROM workbench_source_catalog WHERE matter_id=? AND document_id=?",
                                          (matter_id, source["document_id"])).fetchone()
            if row is None or tuple(row) != (source["source_version_id"], source["source_basis_digest"], source["source_state"]):
                raise WorkspaceProblem("A frozen full-text source is missing, unavailable or changed.")
            if receipt.get("source_set_id") and self.connection.execute(
                "SELECT 1 FROM workbench_source_set_item WHERE matter_id=? AND source_set_id=? AND document_id=?",
                (matter_id, receipt["source_set_id"], source["document_id"])).fetchone() is None:
                raise WorkspaceProblem("A frozen full-text source left the selected source set.")

    def _capture_locked(self, matter_id, run_id, *, candidates):
        db = self.connection
        run = db.execute("SELECT * FROM workbench_review_run WHERE matter_id=? AND run_id=?", (matter_id, run_id)).fetchone()
        if run is None:
            raise WorkspaceProblem("The selected full-text review is no longer available in this matter.")
        run = dict(run)
        if run["run_kind"] != "full" or run["state"] not in {"succeeded", "failed", "cancelled"}:
            raise WorkspaceProblem("Choose exactly one terminal full-text review before synthesizing its findings.")
        settings = db.execute("SELECT policy_json FROM workbench_text_review WHERE run_id=?", (run_id,)).fetchone()
        budget = db.execute("SELECT * FROM workbench_text_review_budget WHERE run_id=?", (run_id,)).fetchone()
        if settings is None or budget is None or budget["legacy"]:
            raise WorkspaceProblem("This review has no compatible versioned full-text ledger. Start a new full-text review.")
        criterion = db.execute("SELECT * FROM workbench_review_criterion_version WHERE matter_id=? AND criterion_version_id=?",
                               (matter_id, run["criterion_version_id"])).fetchone()
        if criterion is None:
            raise WorkspaceProblem("The selected review criterion version is missing.")
        criterion = dict(criterion)
        question = criterion_question(criterion)
        title_row = db.execute("SELECT title FROM workbench_review_criterion WHERE matter_id=? AND criterion_id=?",
                               (matter_id, run["criterion_id"])).fetchone()
        title = "Synthesis: " + (title_row[0] if title_row else "Full-text review")
        if len(title) > 160:
            title = "Full-text review synthesis"
        hashes, sources, outcomes, selected, oversized = {}, [], [], [], []
        source_counts, unit_counts, range_counts, decisions = Counter(), Counter(), Counter(), Counter()
        frozen_source_digest = hashlib.sha256()
        for label, table, order in (("sources", "workbench_text_review_source", "document_id"),
                                   ("units", "workbench_text_review_unit", "document_id,unit_ordinal"),
                                   ("decisions", "workbench_review_decision", "ordinal")):
            hasher = hashlib.sha256()
            for row in db.execute(f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order}", (run_id,)):
                row = dict(row)
                _hash_row(hasher, row)
                if label == "sources":
                    if len(sources) >= ADMISSION["sources"]:
                        raise WorkspaceProblem("The full-text source receipt exceeds its source limit.")
                    sources.append({key: row[key] for key in ("document_id", "source_version_id", "source_basis_digest", "source_state", "state", "inventory_sealed", "unit_count", "text_chars", "chunk_count", "empty_units")})
                    _hash_row(frozen_source_digest, row["document_id"])
                    source_counts[row["state"]] += 1
                elif label == "units":
                    unit_counts[row["state"]] += 1
                else:
                    decisions[row["human_decision"] or "unreviewed"] += 1
            hashes[label] = hasher.hexdigest()
        hasher, ranges = hashlib.sha256(), 0
        for row in db.execute(
            "SELECT c.*,u.text_chars,u.unit_digest,u.citation_json,u.state AS unit_state,s.inventory_sealed,s.state AS source_ledger_state "
            "FROM workbench_text_review_chunk c JOIN workbench_text_review_unit u USING(run_id,document_id,unit_ordinal) "
            "JOIN workbench_text_review_source s USING(run_id,document_id) WHERE c.run_id=? ORDER BY c.cursor", (run_id,)):
            row = dict(row)
            ranges += 1
            if ranges > ADMISSION["ranges"]:
                raise WorkspaceProblem("The full-text range receipt exceeds its fixed enumeration limit.")
            _hash_row(hasher, row)
            if row["state"] != "processed" or row["decision"] != "include":
                range_counts["no_finding" if row["state"] == "processed" and row["decision"] == "exclude" else row["state"]] += 1
                continue
            reason = "candidate"
            if not row["inventory_sealed"] or row["source_ledger_state"] == "invalidated" or row["unit_state"] == "invalidated":
                reason = "unsealed_or_invalidated"
            elif row["text_chars"] > ADMISSION["original_characters"]:
                reason = "oversized_original"
                oversized.append([row["cursor"], row["document_id"], row["unit_ordinal"], row["text_chars"]])
            elif len(selected) >= ADMISSION["findings"]:
                reason = "finding_limit"
            if reason == "candidate":
                locator = read_locator(row["citation_json"])
                if (locator.get("matter_id") != matter_id or locator.get("document_id") != row["document_id"]
                    or locator.get("unit_ordinal") != row["unit_ordinal"] or locator.get("unit_digest") != row["unit_digest"]):
                    raise WorkspaceProblem("A saved finding has an incompatible original locator.")
                # Keep placeholders during validation so identical deterministic
                # admission yields the same metadata without retaining rationale.
                selected.append({"cursor": row["cursor"], "document_id": row["document_id"],
                                 "unit_ordinal": row["unit_ordinal"], "text_chars": row["text_chars"],
                                 "finding_key": row["finding_key"], "locator": locator,
                                 **({"text": row["rationale"]} if candidates else {})})
            outcomes.append([row["cursor"], reason])
        hashes["findings"] = hasher.hexdigest()
        counters = [dict(row) for row in db.execute("SELECT kind,state,count,characters FROM workbench_text_review_counter WHERE run_id=? ORDER BY kind,state", (run_id,))]
        coverage = {"sources": dict(source_counts), "units": dict(unit_counts), "ranges": dict(range_counts),
                    "range_count": ranges, "counters": counters, "budget": dict(budget),
                    "has_gaps": bool(budget["limit_reason"] or source_counts["pending"] or source_counts["unavailable"] or source_counts["invalidated"]
                                     or any(unit_counts[k] for k in ("failed", "empty", "pending", "invalidated"))
                                     or any(source["inventory_sealed"] and source["unit_count"] == 0 for source in sources))}
        receipt = {"version": VERSION, "matter_id": matter_id, "run_id": run_id,
                   "run_state": run["state"], "run_updated_at": run["updated_at"],
                   "question": question, "title": title, "criterion_id": run["criterion_id"], "criterion_version_id": run["criterion_version_id"],
                   "criterion_digest": digest(criterion), "source_set_id": run["source_set_id"],
                   "source_set_digest": self._scope_digest(matter_id, run["source_set_id"]),
                   "sources": sources, "coverage": coverage,
                   "decision_revision_digest": hashes["decisions"],
                   "human_decisions": {"mode": "frozen_context_not_evidence", "counts": dict(decisions),
                                       "notice": "Decision revisions and counts are frozen provenance context. Human notes and decisions do not select findings or become evidence."},
                   "table_digests": hashes, "admission": dict(ADMISSION), "outcomes": outcomes,
                   "oversized_originals": oversized}
        if run["source_set_id"] and receipt["source_set_digest"] != frozen_source_digest.hexdigest():
            raise WorkspaceProblem("The selected source set changed since the full-text review population was frozen.")
        self._validate_sources_locked(matter_id, receipt)
        receipt["snapshot_digest"] = digest({"run": run, "criterion": criterion, "policy": json.loads(settings[0]),
                                             "tables": hashes, "coverage": coverage,
                                             "scope": receipt["source_set_digest"]})
        if encoded_bytes(receipt) > ADMISSION["receipt_bytes"]:
            raise WorkspaceProblem("The complete full-text input receipt exceeds its 400,000-byte persistence limit. No synthesis was admitted.")
        return {"receipt": receipt, "candidates": selected if candidates else []}
