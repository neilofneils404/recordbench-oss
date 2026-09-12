"""Incremental entity discovery from slice-12 frozen unit coverage.

The caller supplies an explicit authorized repository and a current-unit loader.
Each unit commits atomically under source-then-workspace guards. Stopping between
requests leaves pending coverage; a failed recognizer cannot partially save it.
"""
from dataclasses import asdict
import hashlib
import json

from .entity_extractor import DeterministicEntityExtractor
from .workspace_store import WorkspaceProblem


DISCOVERY_BYTE_LIMIT = 16 * 1024 * 1024


class EntityDiscovery:
    def __init__(self, service, *, load_unit, extractor=None, byte_limit=DISCOVERY_BYTE_LIMIT):
        if type(byte_limit) is not int or not 4096 <= byte_limit <= DISCOVERY_BYTE_LIMIT:
            raise ValueError('Use a discovery byte limit between 4096 and 16777216.')
        self.byte_limit = byte_limit
        self.service = service
        self.load_unit = load_unit
        self.extractor = extractor or DeterministicEntityExtractor()
        if (not isinstance(self.extractor.version, str) or not 1 <= len(self.extractor.version) <= 80
                or any(ord(character) < 32 for character in self.extractor.version)):
            raise ValueError('Use a bounded, printable extractor version.')

    def runs(self, matter_id, actor_id):
        with self.service.repository.transaction(matter_id, actor_id) as repo:
            return repo.discovery_runs(matter_id)

    def coverage(self, matter_id, actor_id, run_id):
        with self.service.repository.transaction(matter_id, actor_id) as repo:
            return repo.discovery_coverage(matter_id, run_id, self.extractor.version)

    def step(self, matter_id, actor_id, run_id, *, limit=10, retry=False):
        if not 1 <= limit <= 25:
            raise WorkspaceProblem('Process between 1 and 25 units at a time.')
        service = self.service
        with service.repository.transaction(matter_id, actor_id) as repo:
            repo.require_discovery_run(matter_id, run_id)
            units = repo.discovery_pending(matter_id, run_id, self.extractor.version, limit, retry)
        for unit in units:
            with service.source_guard(), service.repository.transaction(matter_id, actor_id) as repo:
                if not repo.discovery_claimable(matter_id, unit, retry):
                    continue
                used_bytes = repo.discovery_storage_bytes(matter_id)
                if used_bytes + 4096 > self.byte_limit:
                    raise WorkspaceProblem('Entity discovery byte budget reached. Saved work is retained; this unit remains unprocessed.')
                repo.seed_discovery_unit(unit)
                try:
                    if not repo.discovery_source_current(matter_id, unit):
                        raise KeyError('changed frozen source')
                    text, reference = self.load_unit(unit)
                    if (reference['document_id'] != unit['document_id']
                            or reference['source_version_id'] != unit['source_version_id']
                            or hashlib.sha256(text.encode()).hexdigest() != unit['unit_digest']):
                        raise KeyError('changed unit')
                except (KeyError, OSError, ValueError, RuntimeError):
                    repo.discovery_state(unit, 'invalidated', 'Original unit changed or is unavailable; start current-source coverage.')
                    continue
                try:
                    occurrences = self.extractor.extract(text)
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
                    repo.discovery_state(unit, 'failed', 'Extractor failed or returned unsupported output. Retry this unit.')
                    continue
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
                repo.discovery_state(unit, 'processed', '')
        return self.coverage(matter_id, actor_id, run_id)
