"""Manual entity workflows with explicit source and workspace authority."""
from dataclasses import asdict

from .workspace_store import NOTEBOOK_STATUSES, WorkspaceProblem

ENTITY_TYPES = ('person', 'place', 'thing')
ENTITY_STATUSES = NOTEBOOK_STATUSES
REFERENCE_FIELDS = ('document_id', 'source_version_id', 'source_name', 'location',
                    'unit_number', 'chunk_id', 'excerpt_digest', 'excerpt', 'support_token')


class EntityService:
    def __init__(self, repository, *, source_guard, resolve_support, load_note, load_references, validate_references):
        self.repository = repository
        self.source_guard = source_guard
        self.resolve_support = resolve_support
        self.load_note = load_note
        self.load_references = load_references
        self.validate_references = validate_references

    @staticmethod
    def fields(*, display_name, entity_type='person', status='needs_review', aliases=''):
        name = display_name.strip()
        labels = [value.strip() for value in aliases.splitlines() if value.strip()]
        if not name or len(name) > 160 or any(ord(c) < 32 for c in name):
            raise WorkspaceProblem('Enter a display name of 1–160 characters.')
        if entity_type not in ENTITY_TYPES or status not in ENTITY_STATUSES:
            raise WorkspaceProblem('Choose an available entity type and review status.')
        if len(labels) > 30 or any(len(value) > 160 or any(ord(c) < 32 for c in value) for value in labels):
            raise WorkspaceProblem('Use at most 30 aliases, each on its own line with at most 160 characters.')
        return dict(display_name=name, entity_type=entity_type, status=status, aliases=list(dict.fromkeys(labels)))

    def list(self, matter_id, actor_id, *, query='', page=1):
        if len(query) > 200 or not 1 <= page <= 100_000:
            raise WorkspaceProblem('Choose a valid search or page.')
        with self.repository.transaction(matter_id, actor_id) as repo:
            return repo.list(matter_id, query, page)

    def detail(self, matter_id, actor_id, entity_id):
        with self.source_guard(), self.repository.transaction(matter_id, actor_id) as repo:
            entity = repo.get(matter_id, entity_id)
            mentions = repo.mentions(matter_id, entity_id)
            available = self.validate_references(mentions)
            for index, mention in enumerate(mentions):
                mention['available'] = index in available
            note = None
            if entity['notebook_item_id']:
                try:
                    note = self.load_note(matter_id, actor_id, entity['notebook_item_id'])
                except KeyError:
                    pass
            return entity, mentions, repo.history(matter_id, entity_id), note

    def create(self, matter_id, actor_id, *, support='', **values):
        fields = self.fields(**values)
        with self.source_guard(), self.repository.transaction(matter_id, actor_id) as repo:
            reference = self.resolve_support(support) if support else None
            entity = repo.create(matter_id, actor_id, fields)
            added = [repo.add_mention(matter_id, actor_id, entity['entity_id'], reference, 'manual')] if reference else []
            repo.record_history(matter_id, actor_id, entity['entity_id'], 'created', added_mentions=added)
            return entity

    def update(self, matter_id, actor_id, entity_id, *, expected_revision, **values):
        fields = self.fields(**values)
        with self.repository.transaction(matter_id, actor_id) as repo:
            repo.check_revision(matter_id, entity_id, expected_revision)
            repo.save(matter_id, actor_id, entity_id, fields)
            repo.record_history(matter_id, actor_id, entity_id, 'edited')
            return repo.get(matter_id, entity_id)

    def attach(self, matter_id, actor_id, entity_id, *, expected_revision, support):
        with self.source_guard(), self.repository.transaction(matter_id, actor_id) as repo:
            current = repo.check_revision(matter_id, entity_id, expected_revision)
            reference = self.resolve_support(support)
            if repo.has_mention(matter_id, entity_id, support):
                return current
            added = repo.add_mention(matter_id, actor_id, entity_id, reference, 'manual')
            repo.save(matter_id, actor_id, entity_id, current)
            repo.record_history(matter_id, actor_id, entity_id, 'mention attached', added_mentions=[added])
            return repo.get(matter_id, entity_id)

    def remove_mention(self, matter_id, actor_id, entity_id, *, expected_revision, mention_id):
        with self.repository.transaction(matter_id, actor_id) as repo:
            current = repo.check_revision(matter_id, entity_id, expected_revision)
            removed = repo.remove_mention(matter_id, entity_id, mention_id)
            repo.save(matter_id, actor_id, entity_id, current)
            repo.record_history(matter_id, actor_id, entity_id, 'mention removed', removed_mentions=[removed])

    def delete(self, matter_id, actor_id, entity_id, *, expected_revision):
        with self.repository.transaction(matter_id, actor_id) as repo:
            repo.check_revision(matter_id, entity_id, expected_revision)
            repo.delete(matter_id, entity_id)

    def import_note(self, matter_id, actor_id, item_id):
        with self.source_guard(), self.repository.transaction(matter_id, actor_id) as repo:
            existing = repo.imported(matter_id, item_id)
            if existing:
                return existing
            note = self.load_note(matter_id, actor_id, item_id)
            if note.item_type not in ENTITY_TYPES:
                raise WorkspaceProblem('Only supported person, place, or thing notes can be imported.')
            references = self.load_references(matter_id, actor_id, item_id)
            if not references:
                raise WorkspaceProblem('This note has no original source support. Attach a supported passage to a manually created entity instead.')
            prepared = [{key: getattr(reference, key) for key in REFERENCE_FIELDS} for reference in references]
            if self.validate_references(prepared) != frozenset(range(len(prepared))):
                raise WorkspaceProblem('A note passage changed or is unavailable. Review its original support before importing.')
            validated = {reference['support_token']: reference for reference in prepared}
            fields = self.fields(display_name=note.title, entity_type=note.item_type, status=note.status)
            entity = repo.create(matter_id, actor_id, fields, notebook=asdict(note))
            added = [repo.add_mention(matter_id, actor_id, entity['entity_id'], reference, 'notebook')
                     for reference in validated.values()]
            repo.record_history(matter_id, actor_id, entity['entity_id'], 'notebook imported', added_mentions=added)
            return entity


def current_reference_indexes(references, *, load_document, candidate_for, support_tokens):
    """Validate only referenced documents, parsing each once under the source guard.

    Results identify input positions, not tokens: duplicate tokens with differing
    metadata must each pass the exact original-reference comparison.
    """
    grouped = {}
    for index, reference in enumerate(references):
        grouped.setdefault(reference['document_id'], []).append((index, reference))
    available = set()
    for document_id, expected in grouped.items():
        try:
            document = load_document(document_id)
        except KeyError:
            continue
        if document.state != 'ready':
            continue
        units = document.parsed_units()
        candidates = {}
        for index, reference in expected:
            try:
                ordinal = int(reference['chunk_id'].removeprefix('chunk-'))
            except (TypeError, ValueError, AttributeError):
                continue
            if not 1 <= ordinal <= len(units):
                continue
            if ordinal not in candidates:
                candidate = candidate_for(document, units[ordinal - 1], ordinal)
                candidates[ordinal] = (candidate, support_tokens(candidate))
            candidate, tokens = candidates[ordinal]
            current = dict(document_id=candidate.document_id, source_version_id=candidate.source_version_id,
                source_name=candidate.source_name, location=candidate.citation, unit_number=units[ordinal - 1].number,
                chunk_id=candidate.chunk_id, excerpt_digest=candidate.excerpt_digest,
                excerpt=candidate.text[:6000], support_token=reference['support_token'])
            if reference['support_token'] in tokens and all(current[key] == reference[key] for key in REFERENCE_FIELDS):
                available.add(index)
    return frozenset(available)
