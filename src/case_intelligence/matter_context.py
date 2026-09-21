"""Explicit reviewer approvals; no generation, snapshots, or automatic refresh."""
from dataclasses import asdict
import hashlib

from .matter_context_repository import ContextLimit, MatterContextRepository, MAX_BYTES, MAX_ITEMS, serialized
from .workspace_store import WorkspaceProblem

KINDS = ('notebook_item', 'entity', 'assertion')


class ContextConflict(WorkspaceProblem):
    pass


def digest(value):
    return hashlib.sha256(serialized(value).encode()).hexdigest()


class MatterContextService:
    def __init__(self, assertions):
        self.assertions = assertions
        self.entities = assertions.entities
        self.repository = MatterContextRepository(assertions.repository)

    @staticmethod
    def identity(kind, object_id):
        if kind not in KINDS or not isinstance(object_id, str) or not 1 <= len(object_id) <= 80:
            raise WorkspaceProblem('Choose a typed saved record.')

    def _resolve(self, matter_id, actor_id, kind, object_id, budget):
        self.identity(kind, object_id)
        repo = self.repository
        ar = self.assertions.repository
        roles = []
        if kind == 'notebook_item':
            repo.preflight('workbench_notebook_item', matter_id, 'item_id', object_id, budget, limit=1)
            repo.preflight('workbench_notebook_reference', matter_id, 'item_id', object_id, budget)
            record = asdict(self.entities.load_note(matter_id, actor_id, object_id))
            references = [asdict(row) for row in self.entities.load_references(matter_id, actor_id, object_id)]
            version = record['updated_at']
        elif kind == 'entity':
            repo.preflight('workbench_entity', matter_id, 'entity_id', object_id, budget, limit=1)
            repo.preflight('workbench_entity_mention', matter_id, 'entity_id', object_id, budget)
            record = ar.entities.get(matter_id, object_id)
            record.pop('notebook_snapshot', None)
            references = ar.entities.mentions(matter_id, object_id)
            version = record['revision']
        else:
            repo.preflight('workbench_assertion', matter_id, 'assertion_id', object_id, budget, limit=1)
            repo.preflight('workbench_assertion_account', matter_id, 'assertion_id', object_id, budget)
            repo.preflight('workbench_assertion_role', matter_id, 'assertion_id', object_id, budget, limit=100)
            record = ar.get(matter_id, object_id)
            roles = ar.roles(matter_id, object_id, current=False)
            for role in roles:
                repo.preflight('workbench_entity', matter_id, 'entity_id', role['entity_id'], budget, limit=1)
            roles = ar.roles(matter_id, object_id)
            references = ar.accounts(matter_id, object_id)
            version = record['revision']
        available = self.entities.validate_references(references)
        for index, reference in enumerate(references):
            reference['available'] = index in available
        result = dict(record=record, references=references, roles=roles,
            approval=dict(version=version, record=digest(record), support=digest(references), roles=digest(roles)),
            support_state=('No attached sources by design' if not references else
                'Sources available' if len(available) == len(references) else 'Source unavailable or changed'))
        # JSON escaping can expand byte counts, so independently bound serialization.
        budget['serialized'] += len(serialized(result).encode())
        if budget['serialized'] > MAX_BYTES:
            raise ContextLimit('Complete inspection exceeds 512 KiB. Open the original record; reduce support or selection size.')
        return result

    def _row(self, matter_id, actor_id, entry, budget):
        result = dict(entry, current=None, state='Missing', warning='Record deleted or merged; no replacement was selected.')
        try:
            current = self._resolve(matter_id, actor_id, entry['kind'], entry['object_id'], budget)
        except KeyError:
            return result
        except ContextLimit as exc:
            return dict(result, state='Inspection unavailable', warning=str(exc))
        changed = [key for key in ('version', 'record', 'support', 'roles') if entry['approval'].get(key) != current['approval'][key]]
        return dict(result, current=current, state='Changed' if changed else 'Unchanged',
                    warning='Review changes: ' + ', '.join(changed) if changed else '')

    @staticmethod
    def budget():
        return dict(bytes=0, references=0, serialized=0)

    def inspect(self, matter_id, actor_id, *, kind='', object_id='', check_authority=lambda: None):
        with self.entities.source_guard(), self.assertions.repository.transaction(matter_id, actor_id):
            check_authority()
            selection = self.repository.selection(matter_id, actor_id)
            budget = self.budget()
            selection['rows'] = [self._row(matter_id, actor_id, entry, budget) for entry in selection['entries']]
            candidate = None
            if kind or object_id:
                candidate = self._resolve(matter_id, actor_id, kind, object_id, self.budget())
            self.assertions.repository.entities.authorize(matter_id, actor_id)
            check_authority()
            return selection, candidate

    def change(self, matter_id, actor_id, *, expected_revision, action, kind='', object_id='', approval=None,
               check_authority=lambda: None):
        if type(expected_revision) is not int or expected_revision < 0:
            raise WorkspaceProblem('A displayed selection revision is required.')
        if action not in ('add', 'reconcile', 'remove', 'up', 'down', 'clear'):
            raise WorkspaceProblem('Choose a context selection action.')
        if action != 'clear':
            self.identity(kind, object_id)
        with self.entities.source_guard(), self.assertions.repository.transaction(matter_id, actor_id):
            check_authority()
            selection = self.repository.selection(matter_id, actor_id)
            if selection['revision'] != expected_revision:
                raise ContextConflict('Your selection changed in another tab. Nothing was saved. Inspect the current selection and deliberately repeat your choice.')
            entries = selection['entries']
            index = next((i for i, row in enumerate(entries) if (row['kind'], row['object_id']) == (kind, object_id)), None)
            if action == 'clear':
                entries = []
            elif action in ('add', 'reconcile'):
                if (action == 'add' and index is not None) or (action == 'reconcile' and index is None):
                    raise ContextConflict('Selection membership changed. Inspect the current selection before trying again.')
                if action == 'add' and len(entries) >= MAX_ITEMS:
                    raise ContextLimit('Select at most 50 references. This is not a model-fit guarantee.')
                try:
                    current = self._resolve(matter_id, actor_id, kind, object_id, self.budget())
                except KeyError as exc:
                    raise ContextConflict('This record is missing or merged. It cannot be selected or recreated here.') from exc
                if current['approval'] != approval:
                    raise ContextConflict('The record or its dependencies changed after inspection. Review the current basis before approving it.')
                entry = dict(kind=kind, object_id=object_id, approval=current['approval'],
                             selected_by=actor_id, selected_at=self.repository.now())
                if index is None:
                    entries.append(entry)
                else:
                    entries[index] = entry
                # Validate aggregate inspection capacity; retain other approvals exactly.
                budget = self.budget()
                for row in entries:
                    try:
                        self._resolve(matter_id, actor_id, row['kind'], row['object_id'], budget)
                    except KeyError:
                        pass  # Existing missing entries remain removable warnings.
            else:
                if index is None:
                    raise ContextConflict('That reference is no longer selected. It was not re-added.')
                if action == 'remove':
                    entries.pop(index)
                else:
                    target = index + (-1 if action == 'up' else 1)
                    if 0 <= target < len(entries):
                        entries[index], entries[target] = entries[target], entries[index]
            check_authority()
            self.assertions.repository.entities.authorize(matter_id, actor_id)
            return self.repository.save(matter_id, actor_id, selection, entries)
