"""Authorized, content-verified saved work for report compilation.

Callers hold the source mutation guard and workspace lock while collecting a
snapshot. Generation happens after both guards have been released. Source
locators are resolved in bulk, with at most one fallback matter traversal for
legacy references that do not include a document identity.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
import re
from typing import Mapping

from .report_compilation import CompilationMaterial
from .work_product_exports import MAX_EXPORT_TEXT_CHARS, validate_research_basis
from .workspace_store import MAX_REPORT_CITATION_EXCERPT_CHARS, WorkspaceProblem

MAX_SELECTIONS = 20
MAX_MATERIALS = 500
MAX_REFERENCES = 10_000
MAX_CITATION_CHARS = MAX_REPORT_CITATION_EXCERPT_CHARS
# Bound the canonical snapshot before hashing or serialization. Reserve half
# the export capacity for report prose, headings, attribution and generated
# findings. The final rendered report must also respect the export limit.
MAX_TOTAL_CITATION_CHARS = MAX_EXPORT_TEXT_CHARS // 2
_STALE = "Some selected source support changed or lacks an exact saved text version. Reopen that saved work before compiling a report."


class _References:
    def __init__(self, bench, matter):
        self.bench, self.matter = bench, matter
        self.store = bench.source_store(matter)
        self.documents = {}
        self.resolved = {}
        self.bases = {}
        self.digests = {}
        self.reference_counts = Counter()
        self.citation_chars = 0

    def digest(self, document_id, chunk_id, unit):
        key = (document_id, chunk_id)
        if key not in self.digests:
            actual = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
            if unit.excerpt_digest != actual:
                raise WorkspaceProblem(_STALE)
            self.digests[key] = actual
        return self.digests[key]

    def document(self, document_id):
        if document_id not in self.documents:
            try:
                document = self.store.get(document_id)
                self.documents[document_id] = (document, document.parsed_units())
            except (KeyError, OSError, RuntimeError, ValueError) as exc:
                raise WorkspaceProblem(_STALE) from exc
        return self.documents[document_id]

    def _index(self, document_id, wanted):
        document, units = self.document(document_id)
        if document.state != "ready":
            return
        for ordinal, unit in enumerate(units, 1):
            candidate = self.bench._candidate(self.matter, document, unit, ordinal)
            for token in self.bench._support_tokens(candidate) & wanted:
                if token not in self.resolved:
                    if len(unit.text) > MAX_CITATION_CHARS:
                        raise WorkspaceProblem("A selected source passage exceeds the 6,000-character report limit. Choose a smaller supported passage.")
                    # Repeated citations render repeatedly. Charge occurrences,
                    # including frozen ledger checks, rather than unique text.
                    self.citation_chars += len(unit.text) * self.reference_counts[token]
                    if self.citation_chars > MAX_TOTAL_CITATION_CHARS:
                        raise WorkspaceProblem("The selected source passages exceed the report's total citation-text limit. Choose fewer items of saved work; source passages cannot be shortened safely.")
                self.resolved[token] = (document, unit, candidate)
            if wanted <= self.resolved.keys():
                break

    def prepare(self, references):
        if len(references) > MAX_REFERENCES:
            raise WorkspaceProblem("That selection has too many source references. Choose fewer items of saved work.")
        known = {}
        unknown = set()
        for value in references:
            if not isinstance(value, Mapping):
                raise WorkspaceProblem("A saved finding has unreadable source support.")
            token = value.get("support_token", "")
            if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{40}", token):
                raise WorkspaceProblem(_STALE)
            self.reference_counts[token] += 1
            if value.get("matter_id") not in (None, "", self.matter.matter_id):
                raise WorkspaceProblem(_STALE)
            document_id = value.get("document_id")
            if document_id:
                if not isinstance(document_id, str) or not re.fullmatch(r"[0-9a-f]{32}", document_id):
                    raise WorkspaceProblem(_STALE)
                known.setdefault(document_id, set()).add(token)
            else:
                unknown.add(token)
        for document_id, tokens in known.items():
            self._index(document_id, tokens)
            if not tokens <= self.resolved.keys():
                raise WorkspaceProblem(_STALE)
        remaining = unknown - self.resolved.keys()
        if remaining:
            for document in self.store.ready_documents():
                self._index(document.document_id, remaining)
                remaining -= self.resolved.keys()
                if not remaining:
                    break
        if remaining:
            raise WorkspaceProblem(_STALE)

    def resolve(self, value):
        try:
            document, unit, candidate = self.resolved[value["support_token"]]
        except KeyError as exc:
            raise WorkspaceProblem(_STALE) from exc
        actual_digest = self.digest(document.document_id, candidate.chunk_id, unit)
        canonical = {
            "matter_id": self.matter.matter_id, "document_id": document.document_id,
            "source_version_id": document.version_id, "source_name": document.display_name,
            "location": candidate.citation, "unit_number": unit.number,
            "chunk_id": candidate.chunk_id, "excerpt_digest": actual_digest,
            "excerpt": unit.text, "support_token": value["support_token"],
            "kind": "transcript" if candidate.evidence_kind == "transcript" else "source",
        }
        for key in ("matter_id", "document_id", "source_version_id", "source_name", "location",
                    "unit_number", "chunk_id", "excerpt_digest"):
            if value.get(key) not in (None, "") and value[key] != canonical[key]:
                raise WorkspaceProblem(_STALE)
        for key in ("line_start", "line_end"):
            if key in value and value[key] != getattr(unit, key):
                raise WorkspaceProblem(_STALE)
        if value.get("evidence_kind") not in (None, "", candidate.evidence_kind):
            raise WorkspaceProblem(_STALE)
        if value.get("kind") not in (None, "", canonical["kind"]):
            raise WorkspaceProblem(_STALE)
        frozen_digest = value.get("excerpt_digest") == actual_digest
        frozen_excerpt = value.get("excerpt") == unit.text
        if "excerpt" in value and not frozen_excerpt:
            # Existing notebook previews retain a full-unit digest but display
            # a prefix. The digest verifies the complete canonical source text.
            if not frozen_digest or not isinstance(value["excerpt"], str) or not unit.text.startswith(value["excerpt"]):
                raise WorkspaceProblem(_STALE)
        if candidate.evidence_kind == "transcript" and not (frozen_digest or frozen_excerpt):
            # Transcript v2 tokens identify a moment and survive text edits.
            # Legacy digest-bound tokens remain valid only for their exact text.
            if value["support_token"] != self.bench._legacy_support_token(candidate):
                raise WorkspaceProblem(_STALE)
        if len(unit.text) > MAX_CITATION_CHARS:
            raise WorkspaceProblem("A selected source passage exceeds the 6,000-character report limit. Choose a smaller supported passage.")
        return canonical

    def validate_decision_source(self, item):
        document, units = self.document(item.document_id)
        if document.state != "ready" or document.version_id != item.source_version_id or document.display_name != item.source_name:
            raise WorkspaceProblem(_STALE)
        if item.document_id not in self.bases:
            for ordinal, unit in enumerate(units, 1):
                self.digest(document.document_id, f"chunk-{ordinal}", unit)
            # Reuse loaded units: the shared basis helper must not reload a
            # derived file for each decision or source reference.
            cached = replace(document, units=[asdict(unit) for unit in units], units_file="", _units_loader=None)
            self.bases[item.document_id] = self.bench._document_content_basis(cached)
        if not item.source_basis_digest or item.source_basis_digest != self.bases[item.document_id]:
            raise WorkspaceProblem(_STALE)


def snapshot_report_materials(bench, matter, actor: str, selections: tuple[str, ...]) -> tuple[CompilationMaterial, ...]:
    bench.workspace.membership(matter.matter_id, actor)
    if not selections or len(selections) > MAX_SELECTIONS or len(set(selections)) != len(selections):
        raise WorkspaceProblem("Choose between 1 and 20 items of saved work.")
    materials = {}
    validation_references = []
    resolver = _References(bench, matter)

    def add(*, material_id, origin, title, text, citations=(), review_status="needs_review", revision="", author="", date_label="", category="note", review_details=""):
        if not isinstance(text, str):
            raise WorkspaceProblem("A selected finding has unreadable text.")
        if not text.strip():
            return
        material = CompilationMaterial(material_id=material_id, origin=origin,
            title=title, text=text, citations=tuple(citations), review_status=review_status,
            revision=revision, author=author, date_label=date_label, category=category, review_details=review_details)
        if material_id in materials:
            if material != materials[material_id]:
                raise WorkspaceProblem("Overlapping selections contain conflicting versions of saved work.")
            return
        if len(materials) >= MAX_MATERIALS:
            raise WorkspaceProblem("That selection contains more than 500 saved findings. Choose fewer items of saved work.")
        materials[material_id] = material

    def references(values, ledger=None):
        if not isinstance(values, list) or any(not isinstance(value, Mapping) for value in values):
            raise WorkspaceProblem("A saved finding has unreadable source support.")
        result = []
        for value in values:
            if ledger is not None:
                frozen = ledger.get(value.get("support_token"))
                if frozen is None:
                    raise WorkspaceProblem(_STALE)
                # Preserve and later validate supplied locator fields; a forged
                # field may not be overwritten by its valid ledger counterpart.
                for key, supplied in value.items():
                    if key in frozen and supplied not in (None, "") and supplied != frozen[key]:
                        raise WorkspaceProblem(_STALE)
                value = {**value, **frozen}
            result.append(dict(value))
        return tuple(result)

    def coverage(payload, prefix, revision, origin):
        for key, title in (("evidence_notice", "Saved evidence notice"), ("review_scope", "Saved review scope"),
                           ("source_coverage", "Saved source coverage"), ("modality_coverage", "Saved media coverage")):
            value = payload.get(key)
            review_details = ""
            if isinstance(value, str):
                text = value
            elif isinstance(value, Mapping):
                text = str(value.get("notice") or value.get("summary") or "Recorded coverage")
                # Retain original numeric coverage and qualifications rather
                # than replacing them with a generic completeness statement.
                review_details = "Saved coverage values:\n" + json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
            elif value is None:
                continue
            else:
                raise WorkspaceProblem("A saved answer has unreadable coverage information.")
            add(material_id=f"{prefix}:{key}", origin=origin, title=title, text=text,
                revision=revision, category="coverage", author="AI assistance", review_details=review_details)

    def claims(payload, prefix, title, revision, origin, ledger=None, fallback=""):
        if not isinstance(payload, Mapping):
            raise WorkspaceProblem("A saved answer is malformed. Reopen it before compiling a report.")
        values = payload.get("claims", [])
        if not isinstance(values, list):
            raise WorkspaceProblem("A saved answer has unreadable findings.")
        for index, value in enumerate(values):
            if not isinstance(value, Mapping) or not isinstance(value.get("text"), str):
                raise WorkspaceProblem("A saved finding is malformed.")
            add(material_id=f"{prefix}:claim:{index}", origin=origin, title=title,
                text=value["text"], citations=references(value.get("citations", []), ledger), revision=revision,
                review_status="suggested", category="fact", author="AI assistance")
        limitation = payload.get("limitation")
        if limitation is not None:
            if not isinstance(limitation, Mapping) or not isinstance(limitation.get("text"), str):
                raise WorkspaceProblem("A saved answer has an unreadable qualification.")
            add(material_id=f"{prefix}:limitation", origin=origin, title="Saved qualification",
                text=limitation["text"], citations=references(limitation.get("citations", []), ledger),
                revision=revision, category="gap", author="AI assistance")
        missing = payload.get("missing_information")
        if missing is not None and not isinstance(missing, str):
            raise WorkspaceProblem("A saved answer has unreadable missing-information notes.")
        if isinstance(missing, str) and missing.strip():
            add(material_id=f"{prefix}:gap", origin=origin, title="Unanswered question",
                text=missing, citations=references(payload.get("source_matches", []), ledger),
                revision=revision, category="gap", author="AI assistance")
        elif not values and limitation is None:
            text = payload.get("introduction") or fallback
            if text:
                add(material_id=f"{prefix}:gap", origin=origin, title="Saved response requiring review",
                    text=text, citations=references(payload.get("source_matches", []), ledger),
                    revision=revision, category="gap", author="AI assistance")
        coverage(payload, prefix, revision, origin)

    for selection in selections:
        kind, separator, identifier = selection.partition(":")
        if not separator:
            raise WorkspaceProblem("Choose saved work from this matter.")
        if kind == "research":
            job = bench.workspace.research_job(matter.matter_id, actor, identifier)
            if job.state != "succeeded":
                raise WorkspaceProblem("Choose an investigation that has finished.")
            validate_research_basis(matter, job)
            evidence = job.result.get("evidence", [])
            ledger = {}
            for value in evidence:
                token = value.get("support_token")
                if token in ledger and ledger[token] != value:
                    raise WorkspaceProblem(_STALE)
                ledger[token] = value
            validation_references.extend(ledger.values())
            claims(job.result["answer"], job.job_id, job.title, job.updated_at, "research", ledger)
            for index, entry in enumerate(job.result.get("passes", [])):
                if isinstance(entry.get("answer"), Mapping):
                    claims(entry["answer"], f"{job.job_id}:pass:{index}", entry.get("query", job.title), job.updated_at, "research", ledger)
                elif entry.get("text"):
                    add(material_id=f"{job.job_id}:pass-gap:{index}", origin="research", title=entry.get("query") or "Unanswered question",
                        text=entry["text"], citations=references(entry.get("citations", []), ledger),
                        revision=job.updated_at, category="gap", author="AI assistance")
            for index, gap in enumerate(job.result.get("gaps", [])):
                if not isinstance(gap, Mapping):
                    raise WorkspaceProblem("An investigation has unreadable recorded gaps.")
                add(material_id=f"{job.job_id}:recorded-gap:{index}", origin="research",
                    title=gap.get("query") or "Unanswered question", text=gap.get("note") or "No finding was saved.",
                    revision=job.updated_at, category="gap", author="AI assistance")
            coverage_value = job.result.get("coverage", {})
            coverage({"review_scope": coverage_value}, f"{job.job_id}:scope", job.updated_at, "research")
        elif kind == "conversation":
            conversation = bench.workspace.get_conversation_any(matter.matter_id, identifier)
            for message in bench.workspace.messages(matter.matter_id, conversation.conversation_id):
                if message.role == "assistant":
                    claims(message.payload, message.message_id, conversation.title, message.created_at, "assistant", fallback=message.content)
                elif message.role == "user":
                    add(material_id=f"{message.message_id}:user", origin="human", title=f"Conversation context: {conversation.title}",
                        text=message.content, revision=message.created_at, author="Conversation participant",
                        review_status="needs_review", category="conversation_note")
        elif kind in {"notes", "note"}:
            if kind == "notes":
                if identifier != "active":
                    raise WorkspaceProblem("Choose the current team notes.")
                items = bench.workspace.all_notebook_items(matter.matter_id, actor, include_dismissed=False, limit=MAX_MATERIALS + 1)
            else:
                items = (bench.workspace.notebook_item(matter.matter_id, actor, identifier),)
            for item in items:
                if item.status == "dismissed":
                    raise WorkspaceProblem("A selected note was dismissed. Choose current review work.")
                refs = bench.workspace.notebook_references(matter.matter_id, actor, item.item_id)
                add(material_id=item.item_id, origin="human", title=item.title,
                    text=item.body or item.title, citations=tuple(asdict(ref) for ref in refs),
                    review_status=item.status, revision=item.updated_at, author=item.updated_by_name or item.created_by_name,
                    date_label=item.date_label, category=item.item_type)
        elif kind == "review":
            run = bench.workspace.review_run(matter.matter_id, actor, identifier)
            if run.state != "succeeded":
                raise WorkspaceProblem("Choose a source check that has finished.")
            counts = Counter()
            reviewed = total = 0
            for item in bench.workspace.iter_review_decisions_for_report(matter.matter_id, actor, run.run_id):
                total += 1
                counts[item.machine_decision] += 1
                resolver.validate_decision_source(item)
                human = bool(item.human_decision)
                reviewed += human
                reviewer = bench.workspace.get_principal(item.reviewed_by).display_name if item.reviewed_by else "Team reviewer"
                text = f"Machine screening: {item.machine_decision}.\n{item.rationale}"
                if item.error_message:
                    text += f"\nSaved screening limitation: {item.error_message}"
                if human:
                    text += f"\nHuman decision: {item.human_decision}.\nHuman note: {item.human_note or 'None saved.'}"
                else:
                    text += "\nThis saved machine decision has not been reviewed by a person."
                add(material_id=f"{run.run_id}:{item.document_id}", origin="human" if human else "source_review_ai",
                    title=item.source_name, text=text, citations=references(list(item.citations)),
                    review_status="disputed" if (item.machine_decision, item.human_decision) in {("included", "exclude"), ("excluded", "include")} else "needs_review",
                    revision=item.updated_at, author=reviewer if human else "AI screening",
                    category="decision" if human else "gap")
            if total != run.snapshot_count:
                raise WorkspaceProblem("The saved source check is incomplete. Reopen it before compiling.")
            add(material_id=f"{run.run_id}:coverage", origin="source_review_ai", title="Saved source-check coverage",
                text=f"Saved decisions: {total}. Human-reviewed: {reviewed}. Awaiting human review: {total - reviewed}.\n" +
                     "; ".join(f"{key}: {count}" for key, count in sorted(counts.items())),
                revision=run.updated_at, category="coverage", author="AI screening")
        else:
            raise WorkspaceProblem("Choose saved work from this matter.")
    if not materials:
        raise WorkspaceProblem("There are no saved findings in that selection yet. Save an AI answer or add a review note first.")
    all_references = validation_references + [ref for item in materials.values() for ref in item.citations]
    resolver.prepare(all_references)
    for value in validation_references:
        resolver.resolve(value)
    return tuple(replace(item, citations=tuple(resolver.resolve(ref) for ref in item.citations)) for item in materials.values())


def material_snapshot_fingerprint(matter_id: str, selections: tuple[str, ...], materials) -> str:
    value = {"matter": matter_id, "selections": selections, "materials": [asdict(item) for item in materials]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
