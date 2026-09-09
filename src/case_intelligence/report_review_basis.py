"""Build editable Report sections from saved review records, without generation."""

from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

from .workspace_store import ResearchJobRecord, ReviewDecisionRecord, ReviewRunRecord, WorkspaceProblem

MAX_DETAIL_DECISIONS = 50
MAX_DETAIL_CITATIONS = 100


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, Mapping) for item in value):
        raise WorkspaceProblem("The saved review details are malformed. Open the original run to repair them.")
    return tuple(value)


def report_citation(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "transcript" if value.get("evidence_kind") == "transcript" else "source",
        **{key: value.get(key, "") for key in (
            "document_id", "source_version_id", "source_name", "location", "support_token", "excerpt",
        )},
    }


def _section(heading: str, body: str, citations=()) -> dict[str, object]:
    return {"heading": heading, "body": body, "citations": tuple(citations)}


def research_sections(job: ResearchJobRecord) -> tuple[dict[str, object], ...]:
    result = job.result
    ledger = _rows(result.get("evidence"))
    by_token = {str(item.get("support_token", "")): item for item in ledger}
    if "" in by_token or len(by_token) != len(ledger):
        raise WorkspaceProblem("The saved investigation evidence ledger is inconsistent.")

    def citations_for(answer: object) -> tuple[dict[str, object], ...]:
        payload = _mapping(answer)
        tokens: dict[str, None] = {}
        claims = list(_rows(payload.get("claims")))
        if isinstance(payload.get("limitation"), Mapping):
            claims.append(payload["limitation"])
        for claim in claims:
            for citation in _rows(claim.get("citations")):
                token = str(citation.get("support_token", ""))
                if token not in by_token:
                    raise WorkspaceProblem("A finding is missing its saved source support. Open the original investigation.")
                tokens[token] = None
        if len(tokens) > MAX_DETAIL_CITATIONS:
            raise WorkspaceProblem("This finding exceeds the Report citation limit. Export the original investigation.")
        return tuple(report_citation(by_token[token]) for token in tokens)

    answer = _mapping(result.get("answer"))
    supported = answer.get("answerable") is True
    sections = [
        _section("Review question", job.question),
        _section(
            "Investigation findings" if supported else "Investigation outcome: needs review",
            str(result.get("summary") or "No supported synthesis was saved.") + (
                "" if supported else "\n\nThis run did not record an answerable, source-supported synthesis."
            ),
            citations_for(answer),
        ),
    ]
    for index, item in enumerate(_rows(result.get("passes")), 1):
        if index > 100:
            raise WorkspaceProblem("This investigation has too many passes for one Report. Export the original run.")
        sections.append(_section(
            f"Evidence pass {index}",
            f"Search: {item.get('query', '')}\n"
            f"Recorded outcome: {str(item.get('status', 'unknown')).replace('_', ' ')}\n\n"
            f"{item.get('text') or 'No finding was saved for this pass.'}",
            citations_for(item.get("answer")),
        ))
    gaps = [
        f"Search: {item.get('query', '')}\n{item.get('note') or 'Unresolved in the saved run.'}"
        for item in _rows(result.get("gaps"))
    ]
    missing = answer.get("missing_information")
    if missing:
        gaps.append(str(missing))
    sections.append(_section(
        "Gaps and unresolved questions",
        "\n\n".join(gaps) if gaps else
        "No explicit gaps were recorded. This does not establish that all relevant evidence was found.",
    ))
    coverage = _mapping(result.get("coverage"))
    lines = [
        "Scope: " + ("Selected source set" if job.source_set_id else "All searchable sources at the recorded run boundary"),
    ]
    for label, key in (
        ("Search passes", "search_pass_count"),
        ("Returned passages across passes (may repeat)", "candidate_passage_count"),
        ("Unique supporting passages", "evidence_passage_count"),
        ("Distinct supporting sources", "evidence_source_count"),
        ("Sources with searchable text", "searchable_count"),
        ("Sources in recorded coverage", "total_count"),
        ("Excluded sources", "excluded_count"),
    ):
        value = coverage.get(key)
        lines.append(f"{label}: {value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 'Not recorded'}")
    if coverage.get("notice"):
        lines.append(str(coverage["notice"]))
    lines.append("Selected passages are not a count of every page read. This investigation did not check every source.")
    sections.append(_section("Scope and coverage", "\n".join(lines)))
    budget = _mapping(result.get("budget"))
    sections.append(_section(
        "Method and review basis",
        f"Investigation run: {job.job_id}\n"
        f"Saved result revision: {job.updated_at}\n"
        f"Finished: {job.finished_at or 'Not recorded'}\n"
        f"Method: {job.plan.get('method') or 'Not recorded'}\n"
        f"Stop reason: {budget.get('stop_reason') or result.get('stop_reason') or 'Not recorded in this saved run'}\n\n"
        "These sections copy the saved investigation; no new analysis was generated. "
        "Later source or review changes do not rewrite this Report. Verify its citations and preserve the original run export.",
    ))
    return tuple(sections)


def review_sections(
    run: ReviewRunRecord,
    decisions: Sequence[ReviewDecisionRecord],
    *,
    criterion_title: str,
    criterion_version: int,
    instructions: str,
    ledger_path: str,
    reviewer_names: Mapping[str, str] | None = None,
) -> tuple[dict[str, object], ...]:
    if len(decisions) != run.snapshot_count:
        raise WorkspaceProblem("The complete frozen decision population is unavailable. Export or repair the original run.")
    machine = Counter(item.machine_decision for item in decisions)
    human = Counter(item.human_decision for item in decisions)
    sampled = tuple(item for item in decisions if item.validation_sample)

    def disagrees(item: ReviewDecisionRecord) -> bool:
        return (item.machine_decision, item.human_decision) in {("included", "exclude"), ("excluded", "include")}

    disagreements = sum(disagrees(item) for item in decisions)
    sections = [
        _section("Criterion and frozen scope",
            f"{criterion_title}\nCriterion version {criterion_version}: {instructions}\n\n"
            f"Run: {run.run_id}\nCriterion revision: {run.criterion_version_id}\n"
            f"Frozen population: {run.snapshot_count:,} sources\n"
            f"Recorded run state: {run.state}\n"
            "Each source was screened using selected passages. This is not an all-page read."),
        _section("Machine screening results",
            f"Included: {machine['included']:,}\nNot identified: {machine['excluded']:,}\n"
            f"Needs attention: {machine['needs_attention']:,}\nPending: {machine['pending']:,}\n\n"
            "These labels are machine screening outcomes, separate from team validation."),
        _section("Team validation and disagreements",
            f"Decisions with a saved human review: {len(decisions) - human['']:,} of {len(decisions):,}\n"
            f"No saved human review: {human['']:,}\n"
            f"Agreed with machine: {human['agree']:,}\nHuman include: {human['include']:,}\n"
            f"Human exclude: {human['exclude']:,}\nHuman uncertain: {human['uncertain']:,}\n"
            f"Opposing machine/human inclusion labels: {disagreements:,}\n"
            f"Validation sample reviewed: {sum(bool(item.human_decision) for item in sampled):,} of {len(sampled):,}\n\n"
            "Counts describe the decision snapshot copied into this Report. Later reviews do not rewrite it."),
    ]
    selected = sorted(decisions, key=lambda item: (
        not disagrees(item), item.machine_decision != "needs_attention", item.ordinal,
    ))[:MAX_DETAIL_DECISIONS]
    citation_count = 0
    available_citations = sum(len(item.citations) for item in decisions)
    for item in selected:
        available = max(0, MAX_DETAIL_CITATIONS - citation_count)
        citations = tuple(report_citation(value) for value in item.citations[:available])
        citation_count += len(citations)
        detail = (
            f"Source: {item.source_name}\nSource version: {item.source_version_id}\n"
            f"Machine: {item.machine_decision.replace('_', ' ')}\n"
            f"Machine rationale: {item.rationale or 'Not recorded'}\n"
            f"Human decision: {item.human_decision or 'Not reviewed'}\n"
            f"Reviewer: {(reviewer_names or {}).get(getattr(item, 'reviewed_by', None), 'Not recorded')}\n"
            f"Human note: {item.human_note or 'None recorded'}\n"
            f"Human review saved: {item.reviewed_at or 'Not reviewed'}\n"
            f"Decision revision: {item.updated_at}"
        )
        if item.error_message:
            detail += f"\nNeeds attention: {item.error_message}"
        if len(citations) < len(item.citations):
            detail += f"\nCitation detail: {len(citations)} of {len(item.citations)} passages included here; see the original decision ledger."
        sections.append(_section(f"Decision detail {item.ordinal}", detail, citations))
    sections.append(_section(
        "Detail limits and original ledger",
        f"Decision details included: {len(selected):,} of {len(decisions):,}. "
        f"{len(decisions) - len(selected):,} decision details are not reproduced.\n"
        f"Citation entries included: {citation_count:,} of {available_citations:,}. "
        f"{available_citations - citation_count:,} citation entries are not reproduced.\n"
        "Details prioritize opposing human/machine labels and sources needing attention, then frozen source order.\n"
        f"Open the original decision ledger while this matter is available: {ledger_path}\n"
        "Export that ledger for complete decision detail before closing the matter. "
        "This Report is editable work product, not a replacement for the full frozen ledger.",
    ))
    return tuple(sections)
