"""Read saved identities and assertions without creating knowledge or model work."""
from .matter_knowledge_repository import MAX_EXCERPT_CHARS, MatterKnowledgeRepository
from .workspace_store import WorkspaceProblem


class MatterKnowledgeService:
    def __init__(self, assertion_service):
        self.assertions = assertion_service
        self.repository = MatterKnowledgeRepository(assertion_service.repository)

    def page(self, matter_id, actor_id, *, entity_page=1, assertion_page=1):
        if any(type(page) is not int or not 1 <= page <= 100_000
               for page in (entity_page, assertion_page)):
            raise WorkspaceProblem('Choose a valid saved knowledge page.')
        entities = self.assertions.entities
        with entities.source_guard(), self.assertions.repository.transaction(matter_id, actor_id) as authorized:
            identities = self.repository.entities(matter_id, entity_page)
            assertions = self.repository.assertions(matter_id, assertion_page)
            by_entity = {row['entity_id']: row for row in identities['items']}
            by_assertion = {row['assertion_id']: row for row in assertions['items']}
            mentions = self.repository.references(matter_id, list(by_entity))
            accounts = self.repository.references(matter_id, list(by_assertion), accounts=True)
            references = mentions + accounts
            if any(len(row['excerpt']) > MAX_EXCERPT_CHARS for row in references):
                raise WorkspaceProblem('Saved support exceeds the preview limit. Open the complete entity or chronology record to inspect it.')
            available = entities.validate_references(references)
            for index, reference in enumerate(references):
                reference['available'] = index in available
            for row in by_entity.values():
                row.update(mentions=[], reference_total=0, references_omitted=0)
            for row in by_assertion.values():
                row['stances'] = {stance: dict(accounts=[], total=0, omitted=0)
                                  for stance in ('supporting', 'competing')}
            for reference in mentions:
                row = by_entity[reference['entity_id']]
                row['mentions'].append(reference)
                row['reference_total'] = reference['reference_total']
                row['references_omitted'] = row['reference_total'] - len(row['mentions'])
            for reference in accounts:
                group = by_assertion[reference['assertion_id']]['stances'][reference['stance']]
                group['accounts'].append(reference)
                group['total'] = reference['reference_total']
                group['omitted'] = group['total'] - len(group['accounts'])
            authorized.entities.authorize(matter_id, actor_id)
            return dict(entities=identities, assertions=assertions)
