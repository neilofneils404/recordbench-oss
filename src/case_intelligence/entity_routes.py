"""HTTP adapters for the manual entity service; no persistence SQL."""
import json
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .entity_repository import EntityEditConflict
from .entity_service import ENTITY_STATUSES, ENTITY_TYPES
from .workspace_store import WorkspaceProblem


def install_entity_routes(app, *, service_for, discovery_for, authorized_matter, auth_context,
                          require_csrf, templates, base_context, audit,
                          require_response_lease, transfer_response_lease):
    def return_path(slug, value):
        parsed = urlsplit(value)
        prefix = f'/matters/{slug}'
        if (len(value) <= 4000 and not parsed.scheme and not parsed.netloc
                and (parsed.path == prefix or parsed.path.startswith(prefix + '/'))
                and '\\' not in value and not any(ord(c) < 32 for c in value)):
            return value
        return prefix

    def render(request, slug, *, entity_id='', q='', page=1, review_page=1, candidate_page=1, support='', return_to='',
               error='', draft=None, status_code=200):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        service = service_for(matter)
        entity = None
        mentions, history, note = [], [], None
        candidates, reconciliations = [], []
        has_more_candidates = False
        discovery = discovery_for(matter)
        runs = discovery.runs(matter.matter_id, actor, page=review_page) if not entity_id else []
        has_more_reviews = len(runs) > 20
        coverage = [discovery.coverage(matter.matter_id, actor, row['run_id'], limit=0) for row in runs[:20]]
        try:
            entities, total = service.list(matter.matter_id, actor, query=q, page=page)
            if entity_id:
                entity, mentions, history, note = service.detail(matter.matter_id, actor, entity_id)
                candidates, reconciliations, has_more_candidates = service.reconciliation_detail(matter.matter_id, actor, entity_id, page=candidate_page)
        except KeyError as exc:
            raise HTTPException(404, 'Entity or matter is no longer available') from exc
        passage = None
        if support:
            try:
                with service.source_guard(), service.repository.transaction(matter.matter_id, actor):
                    passage = service.resolve_support(support)
            except (KeyError, WorkspaceProblem):
                error = error or 'This passage changed or is unavailable. Return to source review and select a current passage.'
        return_to = return_path(slug, return_to)
        def entity_url(identifier='', target_page=1):
            path = f'/matters/{slug}/entities' + ('/' + identifier if identifier else '')
            return path + '?' + urlencode(dict(q=q, page=target_page, support=support, return_to=return_to))
        return templates.TemplateResponse(request=request, name='workbench_entities.html', context={
            **base_context(request, matter), 'matter': matter, 'entity': entity,
            'entities': entities, 'total': total, 'page': page, 'q': q,
            'mentions': mentions, 'history': [dict(entry, snapshot=json.loads(entry['snapshot_json'])) for entry in history], 'linked_note': note,
            'passage': passage, 'support': support, 'return_to': return_to,
            'entity_url': entity_url, 'entity_types': ENTITY_TYPES, 'entity_statuses': ENTITY_STATUSES,
            'coverage': coverage, 'review_page': review_page, 'has_more_reviews': has_more_reviews,
            'review_page_url': lambda value: f'/matters/{slug}/entities?' + urlencode(dict(q=q, support=support, return_to=return_to, review_page=value)),
            'coverage_url': lambda value: f'/matters/{slug}/entity-discovery/{value}?' + urlencode(dict(q=q, return_to=return_to)),
            'candidate_page': candidate_page, 'has_more_candidates': has_more_candidates,
            'candidate_page_url': lambda value: f'/matters/{slug}/entities/{entity_id}?' + urlencode(dict(q=q, support=support, return_to=return_to, candidate_page=value)),
            'candidates': candidates, 'reconciliations': [dict(row, before=json.loads(row['before_json'])) for row in reconciliations],
            'error': error, 'draft': draft, 'show_assistant_dock': False,
        }, status_code=status_code, headers={'Cache-Control': 'no-store'})

    @app.get('/matters/{slug}/entities', response_class=HTMLResponse)
    @app.get('/matters/{slug}/entities/{entity_id}', response_class=HTMLResponse)
    def entities(request: Request, slug: str, entity_id: str = '',
                 q: str = Query('', max_length=200), page: int = Query(1, ge=1, le=100_000),
                 review_page: int = Query(1, ge=1, le=100_000),
                 candidate_page: int = Query(1, ge=1, le=100_000),
                 support: str = Query('', max_length=40), return_to: str = Query('', max_length=4000)):
        return render(request, slug, entity_id=entity_id, q=q, page=page, review_page=review_page, candidate_page=candidate_page, support=support, return_to=return_to)

    @app.get('/matters/{slug}/entity-discovery/{run_id}', response_class=HTMLResponse)
    def discovery_coverage(request: Request, slug: str, run_id: str,
                           page: int = Query(1, ge=1, le=100_000),
                           source_page: int = Query(1, ge=1, le=100_000),
                           q: str = Query('', max_length=200), return_to: str = Query('', max_length=4000)):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        try:
            coverage = discovery_for(matter).coverage(matter.matter_id, actor, run_id, page=page, source_page=source_page)
        except KeyError as exc:
            raise HTTPException(404, 'Review run is no longer available') from exc
        return_to = return_path(slug, return_to)
        def coverage_url(target_page=page, target_source_page=source_page):
            return f'/matters/{slug}/entity-discovery/{run_id}?' + urlencode(dict(
                page=target_page, source_page=target_source_page, q=q, return_to=return_to))
        return templates.TemplateResponse(request=request, name='workbench_entity_discovery.html', context={
            **base_context(request, matter), 'matter': matter, 'coverage': coverage,
            'q': q, 'return_to': return_to, 'coverage_url': coverage_url,
            'entities_url': f'/matters/{slug}/entities?' + urlencode(dict(q=q, return_to=return_to)),
            'show_assistant_dock': False,
        }, headers={'Cache-Control': 'no-store'})

    @app.post('/matters/{slug}/entities/actions', dependencies=[Depends(require_csrf)])
    def entity_action(request: Request, slug: str, action: str = Form(..., max_length=24),
                      entity_id: str = Form('', max_length=80), expected_revision: int = Form(0, ge=0),
                      display_name: str = Form('', max_length=160), entity_type: str = Form('person', max_length=24),
                      status: str = Form('needs_review', max_length=24), aliases: str = Form('', max_length=5000),
                      support: str = Form('', max_length=40), item_id: str = Form('', max_length=80),
                      target_id: str = Form('', max_length=80), target_revision: int = Form(0, ge=0),
                      operation_id: str = Form('', max_length=80), run_id: str = Form('', max_length=80),
                      mention_id: str = Form('', max_length=80), q: str = Form('', max_length=200),
                      return_to: str = Form('', max_length=4000)):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        service = service_for(matter)
        fields = dict(display_name=display_name, entity_type=entity_type, status=status, aliases=aliases)
        deleted_entity_id = ''
        try:
            if action in ('discover', 'retry_discovery'):
                discovery_for(matter).step(matter.matter_id, actor, run_id, retry=action == 'retry_discovery',
                    on_committed=lambda event: audit(request, 'entity.discovery_unit', 'success' if event['state'] == 'processed' else 'failure',
                        context=auth_context(request), matter=matter, object_type='review_run', object_id=run_id,
                        details={'count': event['count'], 'unit_count': 1,
                                 'state': {'processed': 'completed', 'failed': 'failed', 'invalidated': 'attention'}[event['state']]}))
            elif action in ('merge', 'split', 'alias', 'reject'):
                service.reconcile(matter.matter_id, actor, entity_id, expected_revision=expected_revision,
                    target_id=target_id, target_revision=target_revision, action=action,
                    mention_ids=[mention_id] if mention_id else [])
            elif action == 'undo':
                service.undo(matter.matter_id, actor, operation_id)
            elif action == 'create':
                entity = service.create(matter.matter_id, actor, support=support, **fields)
                entity_id = entity['entity_id']
            elif action == 'update':
                service.update(matter.matter_id, actor, entity_id, expected_revision=expected_revision, **fields)
            elif action == 'attach':
                service.attach(matter.matter_id, actor, entity_id, expected_revision=expected_revision, support=support)
            elif action == 'review_mention':
                service.review_mention(matter.matter_id, actor, entity_id, expected_revision=expected_revision,
                    mention_id=mention_id, status=status)
            elif action == 'remove_mention':
                service.remove_mention(matter.matter_id, actor, entity_id, expected_revision=expected_revision, mention_id=mention_id)
            elif action == 'delete':
                service.delete(matter.matter_id, actor, entity_id, expected_revision=expected_revision)
                deleted_entity_id = entity_id
                entity_id = ''
            elif action == 'import':
                entity_id = service.import_note(matter.matter_id, actor, item_id)['entity_id']
            else:
                raise WorkspaceProblem('Choose an available entity action.')
        except (WorkspaceProblem, KeyError) as exc:
            # Never echo a submitted draft after membership is lost.
            try:
                with service.repository.transaction(matter.matter_id, actor):
                    pass
            except KeyError as denied:
                raise HTTPException(404, 'Entity or matter is no longer available') from denied
            error = str(exc) if isinstance(exc, WorkspaceProblem) else 'The entity, note, or original passage changed or is unavailable. Your submitted text is preserved below.'
            try:
                return render(request, slug, entity_id=entity_id, q=q, support=support, return_to=return_to,
                              error=error, draft=dict(fields, action=action, entity_id=entity_id, expected_revision=expected_revision, target_id=target_id, target_revision=target_revision, mention_id=mention_id),
                              status_code=409 if isinstance(exc, (EntityEditConflict, KeyError)) else 400)
            except HTTPException as gone:
                if gone.status_code != 404:
                    raise
                return render(request, slug, q=q, support=support, return_to=return_to,
                              error=error, draft=dict(fields, action=action if action in ('merge','split','alias','reject') else 'create', entity_id=entity_id, expected_revision=expected_revision, target_id=target_id, target_revision=target_revision, mention_id=mention_id), status_code=409)
        audit(request, 'entity.' + action, 'success', context=auth_context(request), matter=matter,
              object_type='entity', object_id=entity_id or deleted_entity_id or matter.matter_id)
        path = f'/matters/{slug}/entities' + ('/' + entity_id if entity_id else '')
        return RedirectResponse(path + '?' + urlencode(dict(q=q, return_to=return_path(slug, return_to))), status_code=303)

    @app.get('/matters/{slug}/entities/{entity_id}/export', dependencies=[Depends(require_response_lease)])
    def entity_export(request: Request, slug: str, entity_id: str):
        matter = authorized_matter(request, slug)
        try:
            payload = service_for(matter).export(matter.matter_id, auth_context(request).principal_id, entity_id)
        except KeyError as exc:
            raise HTTPException(404, 'Entity not found') from exc
        audit(request, 'entity.export', 'success', context=auth_context(request), matter=matter,
              object_type='entity', object_id=entity_id)
        return transfer_response_lease(request, Response(json.dumps(payload, indent=2), media_type='application/json', headers={
            'Content-Disposition': 'attachment; filename="entity.json"', 'Cache-Control': 'no-store'}))
