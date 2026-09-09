"""Durable coverage and incremental findings for every extracted text range."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3
from typing import Iterable

from .workspace_store import WorkspaceProblem


@dataclass(frozen=True)
class TextReviewPolicy:
    packet_chars: int = 6_000
    overlap_chars: int = 256
    output_tokens: int = 1_200

    def __post_init__(self):
        if type(self.packet_chars) is not int or not 512 <= self.packet_chars <= 6_000:
            raise ValueError("Text review packets must contain 512 to 6,000 characters.")
        if type(self.overlap_chars) is not int or not 0 <= self.overlap_chars < self.packet_chars // 2:
            raise ValueError("Text overlap must be smaller than half a packet.")
        if self.output_tokens != 1_200:
            raise ValueError("Text review uses the shared 1,200-token generation limit.")


DEFAULT_TEXT_POLICY = TextReviewPolicy()


def text_ranges(text: str, policy: TextReviewPolicy = DEFAULT_TEXT_POLICY):
    """Yield canonical coverage plus overlapping context; no suffix is omitted."""
    width = policy.packet_chars - 2 * policy.overlap_chars
    for start in range(0, len(text), width):
        end = min(len(text), start + width)
        packet_start, packet_end = max(0, start - policy.overlap_chars), min(len(text), end + policy.overlap_chars)
        yield start, end, packet_start, packet_end


class FullTextReviewLedger:
    def __init__(self, workspace):
        self.workspace = workspace

    def enabled(self, run_id):
        with self.workspace._lock:
            return self.workspace.connection.execute(
                "SELECT 1 FROM workbench_text_review WHERE run_id=?", (run_id,)
            ).fetchone() is not None

    def enable_locked(self, run_id, *, scope_clause="", scope_parameters=()):
        """Called inside the source-run admission transaction."""
        db = self.workspace.connection
        run = db.execute("SELECT * FROM workbench_review_run WHERE run_id=?", (run_id,)).fetchone()
        db.execute("INSERT INTO workbench_text_review(run_id,policy_json) VALUES (?,?)",
                   (run_id, json.dumps(asdict(DEFAULT_TEXT_POLICY), sort_keys=True)))
        db.execute(
            "INSERT INTO workbench_text_review_source(run_id,document_id,source_version_id,source_basis_digest,"
            "source_name,source_kind,source_state,extraction_note,reported_pages,state) "
            "SELECT ?,c.document_id,c.version_id,c.content_basis_digest,c.display_name,c.kind,c.source_state,"
            "c.state_label,c.page_count,CASE WHEN c.source_state='ready' THEN 'pending' ELSE 'unavailable' END "
            "FROM workbench_source_catalog c WHERE c.matter_id=?" + scope_clause,
            (run_id, run['matter_id'], *scope_parameters),
        )

    @contextmanager
    def writing(self, run, *, allow_cancel=False):
        store = self.workspace
        with store._lock, store.connection:
            store.connection.execute("BEGIN IMMEDIATE")
            current = store.connection.execute("SELECT * FROM workbench_review_run WHERE run_id=?", (run.run_id,)).fetchone()
            if (current is None or current['state'] != 'running' or current['attempts'] != run.attempts
                or current['worker_id'] != run.worker_id or (current['cancellation_requested'] and not allow_cancel)):
                raise WorkspaceProblem("This text review attempt is no longer active.")
            store.membership(run.matter_id, run.actor_id)
            yield store.connection

    def source_current_locked(self, db, run_id, document_id):
        return db.execute("SELECT 1 FROM workbench_text_review_source s JOIN workbench_review_run r ON r.run_id=s.run_id "
            "JOIN workbench_source_catalog c ON c.matter_id=r.matter_id AND c.document_id=s.document_id "
            "WHERE s.run_id=? AND s.document_id=? AND c.source_state='ready' AND c.version_id=s.source_version_id "
            "AND s.source_basis_digest!='' AND c.content_basis_digest=s.source_basis_digest", (run_id, document_id)).fetchone() is not None

    def inventory(self, run, decision, units: Iterable, *, current_source, citation_for=None):
        """Stage metadata in bounded transactions; only a sealed inventory is read."""
        with self.writing(run) as db:
            source = db.execute("SELECT state FROM workbench_text_review_source WHERE run_id=? AND document_id=?",
                                (run.run_id, decision.document_id)).fetchone()
            if source is None:
                raise WorkspaceProblem("The frozen text source is missing.")
            if source['state'] != 'pending':
                return
            if not self.source_current_locked(db, run.run_id, decision.document_id) or not current_source():
                self._invalidate_locked(db, run.run_id, decision.document_id)
                return
            # An interrupted inventory has no findings; rebuild its metadata.
            db.execute("DELETE FROM workbench_text_review_unit WHERE run_id=? AND document_id=?", (run.run_id, decision.document_id))
        unit_count = chars = chunks = empty = 0
        for ordinal, unit in enumerate(units, 1):
            digest = hashlib.sha256(unit.text.encode('utf-8')).hexdigest()
            width = DEFAULT_TEXT_POLICY.packet_chars - 2 * DEFAULT_TEXT_POLICY.overlap_chars
            chunk_count = (len(unit.text) + width - 1) // width
            with self.writing(run) as db:
                db.execute("INSERT INTO workbench_text_review_unit(run_id,document_id,unit_ordinal,unit_number,"
                           "location,unit_digest,text_chars,chunk_count,state,citation_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (run.run_id, decision.document_id, ordinal, unit.number, unit.location, digest,
                            len(unit.text), chunk_count, 'pending' if chunk_count else 'empty',
                            json.dumps(citation_for(unit, ordinal) if citation_for else {}, separators=(',', ':'))))
                cursor_start = db.execute("SELECT COALESCE(max(cursor),0)+1 FROM workbench_text_review_chunk WHERE run_id=?", (run.run_id,)).fetchone()[0]
                db.executemany("INSERT INTO workbench_text_review_chunk(run_id,document_id,unit_ordinal,chunk_ordinal,cursor,"
                               "coverage_start,coverage_end,packet_start,packet_end) VALUES (?,?,?,?,?,?,?,?,?)",
                               ((run.run_id, decision.document_id, ordinal, number, cursor_start + number - 1, *bounds)
                                for number, bounds in enumerate(text_ranges(unit.text), 1)))
            unit_count += 1
            chars += len(unit.text)
            chunks += chunk_count
            empty += not chunk_count
        with self.writing(run) as db:
            if not self.source_current_locked(db, run.run_id, decision.document_id) or not current_source():
                self._invalidate_locked(db, run.run_id, decision.document_id)
                return
            db.execute("UPDATE workbench_text_review_source SET state='inventoried',inventory_sealed=1,unit_count=?,text_chars=?,chunk_count=?,empty_units=? "
                       "WHERE run_id=? AND document_id=?", (unit_count, chars, chunks, empty, run.run_id, decision.document_id))

    def _invalidate_locked(self, db, run_id, document_id):
        db.execute("UPDATE workbench_text_review_source SET state='invalidated' WHERE run_id=? AND document_id=?", (run_id, document_id))
        db.execute("UPDATE workbench_text_review_unit SET state='invalidated',citation_json='{}' WHERE run_id=? AND document_id=?", (run_id, document_id))
        db.execute("UPDATE workbench_text_review_chunk SET state='invalidated',decision='',rationale='',finding_key='' "
                   "WHERE run_id=? AND document_id=?", (run_id, document_id))

    def invalidate(self, run, document_id):
        with self.writing(run, allow_cancel=True) as db:
            self._invalidate_locked(db, run.run_id, document_id)

    def unit_chunks(self, run_id, document_id, ordinal):
        with self.workspace._lock:
            return tuple(dict(row) for row in self.workspace.connection.execute(
                "SELECT c.*,u.unit_digest,u.text_chars FROM workbench_text_review_chunk c JOIN workbench_text_review_unit u "
                "USING(run_id,document_id,unit_ordinal) WHERE c.run_id=? AND c.document_id=? AND c.unit_ordinal=? ORDER BY c.chunk_ordinal",
                (run_id, document_id, ordinal)))

    def record(self, run, decision, chunk, *, state, label='', rationale='', current_source):
        if state not in {'processed', 'failed'} or label not in {'', 'include', 'exclude'}:
            raise ValueError('Invalid text review outcome')
        if state == 'processed' and not label:
            raise ValueError('Processed text needs a verified outcome')
        with self.writing(run) as db:
            if not self.source_current_locked(db, run.run_id, decision.document_id) or not current_source():
                self._invalidate_locked(db, run.run_id, decision.document_id)
                return False
            key = hashlib.sha256((' '.join(rationale.casefold().split())).encode()).hexdigest() if label == 'include' else ''
            changed = db.execute("UPDATE workbench_text_review_chunk SET state=?,decision=?,rationale=?,finding_key=?,attempt=? "
                "WHERE run_id=? AND document_id=? AND unit_ordinal=? AND chunk_ordinal=? AND state='pending'",
                (state, label, rationale[:4_000], key, run.attempts, run.run_id, decision.document_id,
                 chunk['unit_ordinal'], chunk['chunk_ordinal'])).rowcount
            db.execute("UPDATE workbench_text_review_unit SET state=CASE "
                "WHEN EXISTS(SELECT 1 FROM workbench_text_review_chunk c WHERE c.run_id=workbench_text_review_unit.run_id "
                "AND c.document_id=workbench_text_review_unit.document_id AND c.unit_ordinal=workbench_text_review_unit.unit_ordinal AND c.state='pending') THEN 'pending' "
                "WHEN EXISTS(SELECT 1 FROM workbench_text_review_chunk c WHERE c.run_id=workbench_text_review_unit.run_id "
                "AND c.document_id=workbench_text_review_unit.document_id AND c.unit_ordinal=workbench_text_review_unit.unit_ordinal AND c.state='failed') THEN 'failed' ELSE 'processed' END "
                "WHERE run_id=? AND document_id=? AND unit_ordinal=?", (run.run_id, decision.document_id, chunk['unit_ordinal']))
            return bool(changed)

    def source_summary(self, run_id, document_id):
        with self.workspace._lock:
            db = self.workspace.connection
            source = dict(db.execute("SELECT * FROM workbench_text_review_source WHERE run_id=? AND document_id=?", (run_id, document_id)).fetchone())
            source['states'] = dict(db.execute("SELECT state,count(*) FROM workbench_text_review_chunk WHERE run_id=? AND document_id=? GROUP BY state", (run_id, document_id)))
            source['included'] = db.execute("SELECT count(DISTINCT unit_ordinal || ':' || finding_key) FROM workbench_text_review_chunk WHERE run_id=? AND document_id=? AND decision='include' AND state='processed'", (run_id, document_id)).fetchone()[0]
            source['citations'] = tuple(json.loads(row[0]) for row in db.execute(
                "SELECT u.citation_json FROM workbench_text_review_unit u WHERE u.run_id=? AND u.document_id=? AND EXISTS "
                "(SELECT 1 FROM workbench_text_review_chunk c WHERE c.run_id=u.run_id AND c.document_id=u.document_id AND c.unit_ordinal=u.unit_ordinal AND c.decision='include' AND c.state='processed') "
                "ORDER BY u.unit_ordinal LIMIT 12", (run_id, document_id)))
            return source

    def extraction_rows(self, matter_id, actor_id, run_id, *, after='', limit=100):
        self.workspace.review_run(matter_id, actor_id, run_id)
        with self.workspace._lock:
            return tuple(dict(row) for row in self.workspace.connection.execute(
                "SELECT * FROM workbench_text_review_source WHERE run_id=? AND document_id>? ORDER BY document_id LIMIT ?",
                (run_id, after, min(500, max(1, int(limit))))))

    def citation(self, matter_id, actor_id, run_id, document_id, unit_ordinal):
        self.workspace.review_run(matter_id, actor_id, run_id)
        with self.workspace._lock:
            row = self.workspace.connection.execute("SELECT citation_json FROM workbench_text_review_unit WHERE run_id=? AND document_id=? AND unit_ordinal=? AND state!='invalidated'",
                (run_id, document_id, unit_ordinal)).fetchone()
        if row is None:
            raise KeyError(unit_ordinal)
        return json.loads(row[0])

    def coverage(self, matter_id, actor_id, run_id):
        run = self.workspace.review_run(matter_id, actor_id, run_id)
        with self.workspace._lock:
            db = self.workspace.connection
            settings = db.execute("SELECT policy_json FROM workbench_text_review WHERE run_id=?", (run_id,)).fetchone()
            if settings is None:
                return None
            sources = dict(db.execute("SELECT state,count(*) FROM workbench_text_review_source WHERE run_id=? GROUP BY state", (run_id,)))
            unresolved_inventory = db.execute("SELECT count(*) FROM workbench_text_review_source WHERE run_id=? AND source_state='ready' AND inventory_sealed=0", (run_id,)).fetchone()[0]
            units = dict(db.execute("SELECT state,count(*) FROM workbench_text_review_unit WHERE run_id=? GROUP BY state", (run_id,)))
            chunks = dict(db.execute("SELECT state,count(*) FROM workbench_text_review_chunk WHERE run_id=? GROUP BY state", (run_id,)))
            chars = db.execute("SELECT COALESCE(sum(coverage_end-coverage_start),0),COALESCE(sum(CASE WHEN state='processed' THEN coverage_end-coverage_start ELSE 0 END),0) "
                               "FROM workbench_text_review_chunk WHERE run_id=?", (run_id,)).fetchone()
        return {'mode': 'full_text', 'policy': json.loads(settings[0]), 'sources': sources, 'units': units,
                'chunks': chunks, 'inventoried_characters': chars[0], 'processed_characters': chars[1],
                'inventory_complete': unresolved_inventory == 0, 'unresolved_inventory_sources': unresolved_inventory,
                'notice': 'Every extracted text range has its own recorded outcome. Missing extraction and failed analysis remain separate. Completion does not establish that every relevant fact was recognized.'}

    def rows(self, matter_id, actor_id, run_id, *, after=0, limit=100):
        """Keyset-page sealed source inventories without a total population cap.

        Final synthesis consumers bind the terminal run/revision; active-run
        callers must refresh pending rows because outcomes can still change.
        """
        self.workspace.review_run(matter_id, actor_id, run_id)
        with self.workspace._lock:
            return tuple(dict(row) for row in self.workspace.connection.execute(
                "SELECT c.*,u.unit_number,u.location,u.unit_digest,u.citation_json,s.source_name,s.source_version_id,s.source_basis_digest "
                "FROM workbench_text_review_chunk c JOIN workbench_text_review_unit u USING(run_id,document_id,unit_ordinal) "
                "JOIN workbench_text_review_source s USING(run_id,document_id) WHERE c.run_id=? AND s.inventory_sealed=1 AND c.cursor>? ORDER BY c.cursor LIMIT ?",
                (run_id, max(0, int(after)), min(500, max(1, int(limit))))))


def iter_text_export(workspace, matter_id, actor_id, run_id, format_name='json', *, administrator_override=False):
    """Stream one consistent snapshot, including failures and extraction records."""
    import csv
    import io
    workspace.review_run(matter_id, actor_id, run_id, administrator_override=administrator_override)
    db = sqlite3.connect(workspace.path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        run = db.execute("SELECT r.run_id,r.state,r.criterion_version_id,r.source_set_id,r.created_at,r.finished_at,"
            "v.instructions,v.include_guidance,v.exclude_guidance,t.policy_json FROM workbench_review_run r "
            "JOIN workbench_review_criterion_version v ON v.criterion_version_id=r.criterion_version_id "
            "JOIN workbench_text_review t ON t.run_id=r.run_id WHERE r.matter_id=? AND r.run_id=?", (matter_id, run_id)).fetchone()
        if run is None:
            raise KeyError(run_id)
        def records():
            method = dict(run)
            method['policy'] = json.loads(method.pop('policy_json'))
            yield {'record_type': 'method', **method, 'notice': 'Full extracted-text coverage, with overlapping context. Canonical character ranges are not double-counted. Failed, empty, unavailable and invalidated work remains incomplete. Recognition of every relevant fact is not established.'}
            for table, order, kind in (
                ('workbench_text_review_source', 'document_id', 'source'),
                ('workbench_text_review_unit', 'document_id,unit_ordinal', 'unit'),
                ('workbench_text_review_chunk', 'document_id,unit_ordinal,chunk_ordinal', 'range'),
            ):
                cursor = db.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY {order}', (run_id,))
                while batch := cursor.fetchmany(100):
                    workspace.review_run(matter_id, actor_id, run_id, administrator_override=administrator_override)
                    for row in batch:
                        record = {'record_type': kind, **dict(row)}
                        for key in ('policy_json', 'citation_json'):
                            if key in record:
                                record[key[:-5]] = json.loads(record.pop(key))
                        yield record
        if format_name == 'json':
            yield b'{"records":['
            for number, record in enumerate(records()):
                yield ((',' if number else '') + json.dumps(record, ensure_ascii=False, separators=(',', ':'))).encode('utf-8')
            yield b']}'
        elif format_name == 'csv':
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(('Record type', 'Source identifier', 'Unit ordinal', 'Range ordinal', 'State', 'Decision', 'Coverage start', 'Coverage end', 'Saved record JSON'))
            yield output.getvalue().encode('utf-8')
            for record in records():
                output.seek(0); output.truncate(0)
                # All free text is JSON-encoded so cells cannot begin as formulas.
                writer.writerow((record['record_type'], record.get('document_id',''), record.get('unit_ordinal',''),
                    record.get('chunk_ordinal',''), record.get('state',''), record.get('decision',''),
                    record.get('coverage_start',''), record.get('coverage_end',''), json.dumps(record, ensure_ascii=False)))
                yield output.getvalue().encode('utf-8')
        else:
            raise ValueError('Choose JSON or CSV for the full-text ledger.')
    finally:
        db.close()


def process_text_source(bench, run, decision, cancelled):
    """Process every frozen unit in order, resuming only unrecorded ranges."""
    from .generation import EvidenceItem, GenerationRejected
    from .workflow_jobs import ReviewDecisionResult, WorkflowFailure

    ledger = FullTextReviewLedger(bench.workspace)
    matter = bench._matter_by_id(run.matter_id)
    store = bench.source_store(matter)

    def source_identity(document):
        if document.units_file:
            path = store.derived / document.units_file
            if not store._units_file_is_safe(document.units_file):
                return None
            metadata = path.stat()
            return (document.version_id, document.state, document.units_file, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
        return (document.version_id, document.state, bench._document_content_basis(document))

    with store.mutation_guard():
        try:
            document = store.get(decision.document_id)
            valid = (document.state == 'ready' and document.version_id == decision.source_version_id
                     and decision.source_basis_digest and bench._document_content_basis(document) == decision.source_basis_digest)
            identity = source_identity(document)
        except (KeyError, OSError, RuntimeError):
            valid = False
            identity = None
        if not valid or identity is None:
            ledger.invalidate(run, decision.document_id)
            return ReviewDecisionResult('needs_attention', 'The frozen source is unavailable or changed; its replacement was not analyzed.', (), 'Start a new run for the current source.')

    def current_source():
        try:
            current = store.get(decision.document_id)
            return source_identity(current) == identity
        except (KeyError, OSError, RuntimeError):
            return False

    def safe_point():
        if cancelled():
            raise WorkflowFailure('Review cancelled.')
        bench.workspace.membership(run.matter_id, run.actor_id)

    def citation_for(unit, ordinal):
        return bench._workflow_citation_payload(bench._citation(matter, bench._candidate(matter, document, unit, ordinal)))

    def inventory_units():
        for unit in document.iter_parsed_units():
            safe_point()
            yield unit

    ledger.inventory(run, decision, inventory_units(), current_source=current_source, citation_for=citation_for)
    version = bench.workspace.review_criterion_version(run.matter_id, run.criterion_version_id)
    for ordinal, unit in enumerate(document.iter_parsed_units(), 1):
        safe_point()
        chunks = ledger.unit_chunks(run.run_id, decision.document_id, ordinal)
        if chunks and (chunks[0]['unit_digest'] != hashlib.sha256(unit.text.encode()).hexdigest() or not current_source()):
            ledger.invalidate(run, decision.document_id)
            break
        for chunk in chunks:
            if chunk['state'] != 'pending':
                continue
            safe_point()
            packet = unit.text[chunk['packet_start']:chunk['packet_end']]
            evidence = (EvidenceItem('S1', document.display_name, unit.location, packet,
                        'transcript' if document.media_type.startswith(('audio/', 'video/')) else 'document',
                        document_id=decision.document_id),)
            state, label = 'failed', ''
            rationale = 'This text range could not be classified; direct review is required.'
            try:
                classified = bench.generator.classify_source(criterion=version.instructions,
                    include_guidance=version.include_guidance, exclude_guidance=version.exclude_guidance, evidence=evidence)
                if classified.decision not in {'include', 'exclude'} or (classified.decision == 'include' and classified.used_evidence_ids != ('S1',)):
                    raise GenerationRejected('Text classification did not retain exact source support')
                state, label, rationale = 'processed', classified.decision, classified.rationale
            except Exception:
                pass
            safe_point()
            with store.mutation_guard():
                if not ledger.record(run, decision, chunk, state=state, label=label, rationale=rationale, current_source=current_source):
                    break
    with store.mutation_guard():
        safe_point()
        if not current_source() or bench._document_content_basis(store.get(decision.document_id)) != decision.source_basis_digest:
            ledger.invalidate(run, decision.document_id)
        summary = ledger.source_summary(run.run_id, decision.document_id)
    states = summary['states']
    incomplete = summary['state'] != 'inventoried' or bool(summary['empty_units']) or not summary['unit_count'] or any(states.get(key) for key in ('failed', 'pending', 'invalidated'))
    label = 'included' if summary['included'] else 'needs_attention' if incomplete else 'excluded'
    rationale = (f"Reviewed {states.get('processed', 0):,} of {summary['chunk_count']:,} extracted text ranges "
        f"across {summary['unit_count']:,} units. {summary['included']:,} distinct supported findings; "
        f"{states.get('failed', 0):,} failed ranges; {states.get('pending', 0):,} pending; "
        f"{summary['empty_units']:,} empty units. See the full-text ledger for every recorded range.")
    return ReviewDecisionResult(label, rationale, summary['citations'],
        'Extraction or text-analysis gaps require direct review.' if incomplete else '')
