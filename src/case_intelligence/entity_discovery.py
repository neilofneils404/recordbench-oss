"""Incremental entity discovery from slice-12 frozen unit coverage.

The caller supplies an explicit authorized repository and a current-unit loader.
Each unit commits atomically under source-then-workspace guards. Stopping between
requests leaves pending coverage; a failed recognizer cannot partially save it.
"""
from dataclasses import asdict
from itertools import islice
import hashlib
import json

from .entity_extractor import DeterministicEntityExtractor
from .workspace_store import AUTOMATIC_DISCOVERY_PRINCIPAL, WorkspaceProblem


DISCOVERY_BYTE_LIMIT = 16 * 1024 * 1024
LOAD_ERRORS = (KeyError, OSError, ValueError, RuntimeError, TypeError)


class DiscoveryStopped(Exception):
    """A source read abandoned for shutdown; deliberately not a load error."""


class RunLedger:
    """Coverage recorded against one sealed criterion review run."""

    @staticmethod
    def seed(repo, unit):
        repo.seed_discovery_unit(unit)

    @staticmethod
    def current(repo, matter_id, unit):
        return repo.discovery_source_current(matter_id, unit)

    @staticmethod
    def state(repo, unit, state, note):
        repo.discovery_state(unit, state, note)


class AutomaticLedger:
    """Coverage recorded per current source version; units are sealed up front."""

    @staticmethod
    def seed(repo, unit):
        pass

    @staticmethod
    def current(repo, matter_id, unit):
        return repo.auto_discovery_source_current(matter_id, unit)

    @staticmethod
    def state(repo, unit, state, note):
        repo.auto_discovery_state(unit, state, note)


class EntityDiscovery:
    def __init__(self, service, *, load_unit=None, load_units=None, load_document=None, extractor=None,
                 byte_limit=DISCOVERY_BYTE_LIMIT):
        if type(byte_limit) is not int or not 4096 <= byte_limit <= DISCOVERY_BYTE_LIMIT:
            raise ValueError('Use a discovery byte limit between 4096 and 16777216.')
        self.byte_limit = byte_limit
        self.service = service
        self.load_unit = load_unit
        self.load_units = load_units or self._load_singles
        # load_document(document_id, source_version_id, ordinals=None) yields
        # (ordinal, text, reference) for the current version, in order.
        self.load_document = load_document
        self.extractor = extractor or DeterministicEntityExtractor()
        if (not isinstance(self.extractor.version, str) or not 1 <= len(self.extractor.version) <= 80
                or any(ord(character) < 32 for character in self.extractor.version)):
            raise ValueError('Use a bounded, printable extractor version.')

    def runs(self, matter_id, actor_id, *, page=1):
        with self.service.repository.transaction(matter_id, actor_id) as repo:
            return repo.discovery_runs(matter_id, page)

    def coverage(self, matter_id, actor_id, run_id, *, page=1, source_page=1, limit=50):
        if not 1 <= page <= 100000 or not 1 <= source_page <= 100000 or limit not in (0, 50):
            raise WorkspaceProblem('Choose a valid discovery coverage page.')
        with self.service.repository.transaction(matter_id, actor_id) as repo:
            return repo.discovery_coverage(matter_id, run_id, self.extractor.version, page=page, source_page=source_page, limit=limit)

    def _load_singles(self, units):
        for unit in units:
            try:
                loaded = self.load_unit(unit)
            except (KeyError, OSError, ValueError, RuntimeError):
                loaded = None
            yield unit, loaded

    def step(self, matter_id, actor_id, run_id, *, limit=10, retry=False, on_committed=None):
        if not 1 <= limit <= 25:
            raise WorkspaceProblem('Process between 1 and 25 units at a time.')
        service = self.service
        with service.repository.transaction(matter_id, actor_id) as repo:
            repo.require_discovery_run(matter_id, run_id)
            units = repo.discovery_pending(matter_id, run_id, self.extractor.version, limit, retry)
        # Stream requested ordinals once per document under the same source
        # guard; retain only the current unit, not a batch of full texts.
        with service.source_guard():
            for unit, loaded in self.load_units(units):
                with service.repository.transaction(matter_id, actor_id) as repo:
                    if not repo.discovery_claimable(matter_id, unit, retry):
                        continue
                    state, count = self._process_unit(repo, matter_id, actor_id, unit, loaded, RunLedger)
                if on_committed is not None:
                    on_committed(dict(run_id=run_id, document_id=unit['document_id'],
                        unit_ordinal=unit['unit_ordinal'], state=state, count=count))
        return self.coverage(matter_id, actor_id, run_id, limit=0)

    def automatic_step(self, matter_id, *, unit_limit=25, document_limit=5, audit_unit=None, should_stop=None):
        """Discover suggestions in newly ready sources without a person or a model.

        Each source's current version and extracted basis is inventoried once
        (unit ordinals and digests); later steps load only pending ordinals.
        Returns (units handled, sources sealed); either being non-zero is
        progress. The repository must authorize the automatic-discovery
        principal. audit_unit(event) is called inside each unit's transaction,
        so its content-free record commits atomically with the unit. The
        suggestion byte budget is recounted inside each unit's transaction.
        should_stop() is checked before each source and for every unit read
        or processed, so shutdown never races the source stores this step
        reads. A loader may also raise DiscoveryStopped mid-read (for example
        while indexing a large derived-text file); the step then returns
        without sealing anything partial.
        """
        if self.load_document is None:
            raise ValueError('Automatic discovery needs a whole-document loader.')
        service = self.service
        actor_id = AUTOMATIC_DISCOVERY_PRINCIPAL
        version = self.extractor.version
        handled = sealed = 0
        stopping = should_stop or (lambda: False)
        with service.repository.transaction(matter_id, actor_id) as repo:
            documents = repo.auto_discovery_documents(matter_id, version, document_limit)
        with service.source_guard():
            for document in documents:
                if handled >= unit_limit or stopping():
                    break
                document_id = document['document_id']
                if not document['sealed']:
                    inventory, state, note = [], 'processed', ''
                    try:
                        for ordinal, text, reference in self.load_document(
                                document_id, document['source_version_id']):
                            if stopping():
                                # Unsealed: the next run inventories this source again.
                                return handled, sealed
                            if reference['source_version_id'] != document['source_version_id']:
                                raise KeyError('changed source')
                            inventory.append((ordinal, hashlib.sha256(text.encode()).hexdigest()))
                    except DiscoveryStopped:
                        return handled, sealed
                    except LOAD_ERRORS:
                        inventory, state = [], 'failed'
                        note = 'Searchable text was unavailable for automatic discovery.'
                    with service.repository.transaction(matter_id, actor_id) as repo:
                        if not repo.auto_discovery_source_current(matter_id, dict(document, matter_id=matter_id)):
                            continue
                        if repo.seal_auto_discovery(matter_id, document, version, inventory, state, note):
                            sealed += 1
                with service.repository.transaction(matter_id, actor_id) as repo:
                    pending = repo.auto_discovery_pending(matter_id, document, version, unit_limit - handled)
                if not pending:
                    continue
                wanted = {row['unit_ordinal']: row for row in pending}

                def process(ordinal, loaded):
                    """Commit one unit; False when the byte budget stops the step."""
                    unit = wanted.pop(ordinal)
                    with service.repository.transaction(matter_id, actor_id) as repo:
                        if not repo.auto_discovery_claimable(unit):
                            return None
                        try:
                            state, count = self._process_unit(repo, matter_id, actor_id, unit,
                                                              loaded, AutomaticLedger)
                        except WorkspaceProblem:
                            # Budget reached: saved work stays; remaining units stay pending.
                            return False
                        if audit_unit is not None:
                            audit_unit(dict(document_id=document_id, unit_ordinal=ordinal,
                                            state=state, count=count))
                    return True

                # Each unit is processed as soon as it is read, so at most one
                # unit's text is held at a time. Only the reader's own errors
                # mean unavailable text; processing errors propagate.
                try:
                    units = iter(self.load_document(document_id, document['source_version_id'], sorted(wanted)))
                except DiscoveryStopped:
                    return handled, sealed
                except LOAD_ERRORS:
                    units = iter(())
                while True:
                    try:
                        ordinal, text, reference = next(units)
                    except StopIteration:
                        break
                    except DiscoveryStopped:
                        return handled, sealed
                    except LOAD_ERRORS:
                        break
                    if stopping():
                        return handled, sealed
                    if ordinal not in wanted:
                        continue
                    outcome = process(ordinal, (text, reference))
                    del text
                    if outcome is False:
                        return handled, sealed
                    if outcome:
                        handled += 1
                # Units the reader did not produce are recorded as unavailable.
                for ordinal in sorted(wanted):
                    if stopping():
                        return handled, sealed
                    outcome = process(ordinal, None)
                    if outcome is False:
                        return handled, sealed
                    if outcome:
                        handled += 1
        return handled, sealed

    def prune_automatic(self, matter_id):
        """Drop ledger rows for removed sources; called once per matter per pass."""
        with self.service.repository.transaction(matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL) as repo:
            return repo.prune_auto_discovery(matter_id)

    def retry_automatic(self, matter_id, actor_id):
        """A reviewer's request to retry automatic coverage that failed."""
        with self.service.repository.transaction(matter_id, actor_id) as repo:
            return repo.retry_auto_discovery(matter_id, self.extractor.version)

    def automatic_progress(self, matter_id):
        with self.service.repository.transaction(matter_id, AUTOMATIC_DISCOVERY_PRINCIPAL) as repo:
            return repo.auto_discovery_progress(matter_id, self.extractor.version)

    def _process_unit(self, repo, matter_id, actor_id, unit, loaded, ledger):
        service = self.service
        # Counted inside the admitting transaction, so concurrent writers are included.
        used_bytes = repo.discovery_storage_bytes(matter_id)
        if used_bytes + 4096 > self.byte_limit:
            raise WorkspaceProblem('Entity discovery byte budget reached. Saved work is retained; this unit remains unprocessed.')
        ledger.seed(repo, unit)
        try:
            if not ledger.current(repo, matter_id, unit):
                raise KeyError('changed frozen source')
            if loaded is None:
                raise KeyError('unavailable unit')
            text, reference = loaded
            if (reference['document_id'] != unit['document_id']
                    or reference['source_version_id'] != unit['source_version_id']
                    or hashlib.sha256(text.encode()).hexdigest() != unit['unit_digest']):
                raise KeyError('changed unit')
        except (KeyError, OSError, ValueError, RuntimeError):
            ledger.state(repo, unit, 'invalidated', 'Original unit changed or is unavailable; start current-source coverage.')
            return 'invalidated', 0
        try:
            occurrences = list(islice(self.extractor.extract(text), 1001))
            if len(occurrences) > 1000:
                raise ValueError('bounded output exceeded')
            classifications = {}
            for occurrence in occurrences:
                span = (occurrence.start, occurrence.end)
                if span in classifications and classifications[span] != occurrence.kind:
                    raise ValueError('extractor must resolve same-span classifications')
                classifications[span] = occurrence.kind
                if (not 0 <= occurrence.start < occurrence.end <= len(text)
                        or text[occurrence.start:occurrence.end] != occurrence.label
                        or len(occurrence.label) > 160
                        or occurrence.kind not in ('person', 'organization', 'identifier', 'thing', 'date')):
                    raise ValueError('unsupported occurrence')
                service.fields(display_name=occurrence.label, entity_type=occurrence.kind, status='suggested')
                if len(json.dumps(occurrence.date)) > 1000:
                    raise ValueError('date metadata exceeded its bound')
                if occurrence.kind == 'date':
                    metadata = occurrence.date
                    if (not isinstance(metadata, dict) or metadata.get('raw') != occurrence.label
                            or metadata.get('normalized') is not None
                            or not isinstance(metadata.get('ambiguity'), str)
                            or not metadata['ambiguity']
                            or (metadata.get('timezone') is not None
                                and (not isinstance(metadata['timezone'], str)
                                     or not occurrence.label.endswith(metadata['timezone'])))):
                        raise ValueError('unsupported date normalization')
                elif occurrence.date is not None:
                    raise ValueError('unexpected date metadata')
        except Exception:
            # Do not persist extractor exception text, which may include
            # source content or provider internals.
            ledger.state(repo, unit, 'failed', 'Extractor failed or returned unsupported output. Retry this unit.')
            return 'failed', 0
        prepared = []
        keys = set()
        for occurrence in occurrences:
            key = hashlib.sha256(json.dumps([unit['document_id'], unit['source_version_id'],
                unit['unit_ordinal'], unit['unit_digest'], occurrence.start, occurrence.end], separators=(',', ':')).encode()).hexdigest()
            if key not in keys and not repo.has_discovery_receipt(matter_id, key):
                keys.add(key)
                prepared.append((key, occurrence))
        # Conservatively reserve for entity, mention, receipt, indexes,
        # and the escaped source/occurrence copies in delta history.
        reference_bytes = len(json.dumps(reference).encode('utf-8'))
        required_bytes = 4096 + sum(32768 + 4 * reference_bytes
            + 4 * len(json.dumps(asdict(occurrence)).encode('utf-8')) for _, occurrence in prepared)
        if used_bytes + required_bytes > self.byte_limit:
            raise WorkspaceProblem('Entity discovery byte budget reached. Saved work is retained; this unit remains unprocessed.')
        for key, occurrence in prepared:
            if repo.discovery_seen(matter_id, key):
                continue
            fields = service.fields(display_name=occurrence.label,
                entity_type=occurrence.kind, status='suggested')
            entity = repo.create(matter_id, actor_id, fields)
            repo.mark_extracted(matter_id, entity['entity_id'], self.extractor.version)
            added = repo.add_mention(matter_id, actor_id, entity['entity_id'], reference, 'extraction')
            added = repo.annotate_occurrence(matter_id, added['mention_id'], key, self.extractor.version, occurrence)
            repo.record_history(matter_id, actor_id, entity['entity_id'], 'extracted', added_mentions=[added])
        ledger.state(repo, unit, 'processed', '')
        return 'processed', len(prepared)
