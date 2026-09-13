"""Newly authored, bounded Pump Cedar quality challenges; no private material.

Gold labels are human-authored relevance judgments, not classifier outputs.
Variants probe wording and placement; they are not independent sampled matters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

SUITE = "pump-cedar-workflow-quality-v1"
CRITERION = ("Include sources describing the exercise pressure discrepancy, related "
             "maintenance, or evidence establishing whether the discrepancy was resolved.")
FOLLOW_UP = ("What can we establish about the discrepancy, what happened afterward, "
             "and what remains unverified?")
UNSUPPORTED_QUESTION = "What purchase order number authorized the sensor replacement?"


@dataclass(frozen=True)
class QualitySource:
    case_id: str
    challenge: str
    title: str
    units: tuple[str, ...]
    relevant: bool
    reason: str
    evidence_kind: str = "document"


def sources() -> tuple[QualitySource, ...]:
    base = (
        ("inspection", "Inspection note", (
            "During a training exercise, Pump Cedar showed an 18 psi reading while a reference gauge showed 12 psi. "
            "The operator paused the exercise. The reason for the difference was not yet established.",
        ), True, "Initial discrepancy and pause; cause is not established.", "document"),
        ("maintenance", "Maintenance entry", (
            "A technician replaced Pump Cedar's sensor after the exercise. "
            "The entry does not record a follow-up comparison against the reference gauge.",
        ), True, "Later maintenance and a specifically documented confirmation gap.", "document"),
        ("comparison", "Calibration comparison", (
            "The exercise display exceeded the reference gauge by 6 psi.",
            "The maintenance entry lacks a documented verification measurement.",
        ), True, "Paraphrased corroboration and missing documented verification on separate pages.", "document"),
        ("inventory", "Break-room inventory", (
            "The inventory lists four cups and two chairs. "
            "It contains no equipment measurements or maintenance observations.",
        ), False, "Unrelated inventory; shared exclusion words do not establish relevance.", "document"),
        ("recollection", "Staff recollection recording", (
            "I saw the operator stop the exercise after comparing two readings. "
            "I did not watch the sensor replacement or any later measurement.",
        ), True, "Limited observation of the pause; no firsthand observation of later work.", "transcript"),
    )
    variants = {
        "baseline": {},
        "identifier": {"Pump Cedar": "Pump CEDAR-018"},
        "paraphrase": {
            "showed an 18 psi reading while a reference gauge showed 12 psi":
                "displayed 18 psi; the independent reference read 12 psi",
            "replaced Pump Cedar's sensor": "installed a replacement sensor in Pump Cedar",
            "exceeded the reference gauge by 6 psi": "was 6 psi above the reference gauge",
            "does not record a follow-up comparison": "contains no documented later comparison",
        },
        "transcript_wording": {
            "I saw the operator stop the exercise after comparing two readings.":
                "After looking at the two readings, the operator halted the exercise; I saw that.",
            "I did not watch the sensor replacement or any later measurement.":
                "I did not see the sensor being replaced, and I did not observe a subsequent measurement.",
        },
        "late_page": {},
        "repeated_support": {},
    }
    result = []
    for challenge, replacements in variants.items():
        for key, title, units, relevant, reason, kind in base:
            texts = list(units)
            for old, new in replacements.items():
                texts = [text.replace(old, new) for text in texts]
            if challenge == "late_page" and key == "comparison":
                texts = ["Synthetic page intentionally contains no substantive observation."] * 13 + texts
            if challenge == "repeated_support" and relevant:
                texts = texts + texts
            result.append(QualitySource(f"{challenge}-{key}", challenge, title, tuple(texts), relevant, reason, kind))
    return tuple(result)


def fingerprint() -> str:
    return hashlib.sha256(json.dumps({"suite": SUITE, "criterion": CRITERION,
        "sources": [asdict(item) for item in sources()]}, sort_keys=True).encode()).hexdigest()


def classification_metrics(predictions: dict[str, str], cases=None) -> dict:
    """Missing/rejected decisions stay explicit and count against relevant recall.

    Precision uses only actual include decisions. Conditional recall excludes
    unresolved cases; conservative recall includes them in the gold denominator.
    No statistical interval is inferred from correlated variants of one matter.
    """
    cases = tuple(sources() if cases is None else cases)
    if set(predictions) - {case.case_id for case in cases}:
        raise ValueError("Predictions contain unknown gold source IDs.")
    if any(value not in {"include", "not_identified", "needs_attention"} for value in predictions.values()):
        raise ValueError("Unknown classification outcome.")
    tp, fp, fn, tn, unresolved, unresolved_relevant = ([], [], [], [], [], [])
    for case in cases:
        decision = predictions.get(case.case_id, "needs_attention")
        if decision == "needs_attention":
            unresolved.append(case.case_id)
            if case.relevant:
                unresolved_relevant.append(case.case_id)
        elif decision == "include":
            (tp if case.relevant else fp).append(case.case_id)
        else:
            (fn if case.relevant else tn).append(case.case_id)
    ratio = lambda a, b: a / b if b else None
    return {"sources": len(cases), "gold_relevant": sum(case.relevant for case in cases),
        "true_positive": len(tp), "false_positive": len(fp), "false_negative": len(fn),
        "true_negative": len(tn), "false_negative_ids": fn,
        "unresolved_ids": unresolved, "unresolved_relevant_ids": unresolved_relevant,
        "precision": ratio(len(tp), len(tp) + len(fp)),
        "recall": ratio(len(tp), sum(case.relevant for case in cases)),
        "conditional_recall": ratio(len(tp), len(tp) + len(fn)),
        "uncertainty": "Correlated authored variants of one fictional matter; population precision/recall and statistical confidence are unqualified."}


# Semantic dimensions for a reviewer to score 0 (wrong/missing), 1 (partial),
# or 2 (clear and correct), after checking the cited originals. Do not score
# with exact prose matching, regexes, or the same model being evaluated.
USEFULNESS_RUBRIC = {
    "initial_concern": "Identifies the 18 versus 12 psi discrepancy and the paused exercise; preserves quantities.",
    "later_action": "Separates later sensor replacement from the earlier discrepancy; does not equate replacement with resolution.",
    "unverified_confirmation": "Explains that a later reference comparison is undocumented; does not assert that none occurred or that the discrepancy remained.",
    "observation_limits": "Keeps the recollection's firsthand limits and transcript uncertainty; does not infer speaker identity.",
    "agreement_conflict": "Identifies compatible corroboration; does not invent a conflict among the supplied accounts or choose an unsupported explanation.",
    "consolidation": "Combines repeated claims while retaining original support and meaningful qualifications.",
    "unsupported_premise": "Abstains on the nonexistent purchase-order number without invented number, citation, or negative factual assertion.",
}
