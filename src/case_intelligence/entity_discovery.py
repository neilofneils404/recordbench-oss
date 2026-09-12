"""Incremental entity discovery from slice-12 frozen unit coverage.

The caller supplies an explicit authorized repository and a current-unit loader.
Each unit commits atomically under source-then-workspace guards. Stopping between
requests leaves pending coverage; a failed recognizer cannot partially save it.
"""
import hashlib
import json

from .entity_extractor import DeterministicEntityExtractor
from .workspace_store import WorkspaceProblem


class EntityDiscovery:
    def __init__(self, service, *, load_unit, extractor=None):
        self.service = service
        self.load_unit = load_unit
        self.extractor = extractor or DeterministicEntityExtractor()

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
            repo.discovery_inventory(matter_id, run_id, self.extractor.version)
            units = repo.discovery_pending(matter_id, run_id, self.extractor.version, limit, retry)
        for unit in units:
            with service.source_guard(), service.repository.transaction(matter_id, actor_id) as repo:
                if not repo.discovery_claimable(matter_id, unit, retry):
                    continue
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
                    for occurrence in occurrences:
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
                for occurrence in occurrences:
                    key = hashlib.sha256(json.dumps([unit['document_id'], unit['source_version_id'],
                        unit['unit_ordinal'], unit['unit_digest'], occurrence.start, occurrence.end], separators=(',', ':')).encode()).hexdigest()
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
