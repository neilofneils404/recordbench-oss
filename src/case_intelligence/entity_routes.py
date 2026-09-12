"""HTTP adapters for the manual entity service; no persistence SQL."""
import json
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .entity_repository import EntityEditConflict
from .entity_service import ENTITY_STATUSES, ENTITY_TYPES
from .workspace_store import WorkspaceProblem


def install_entity_routes(app, *, service_for, authorized_matter, auth_context,
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

    def render(request, slug, *, entity_id='', q='', page=1, support='', return_to='',
               error='', draft=None, status_code=200):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        service = service_for(matter)
        entity = None
        mentions, history, note = [], [], None
        try:
            entities, total = service.list(matter.matter_id, actor, query=q, page=page)
            if entity_id:
                entity, mentions, history, note = service.detail(matter.matter_id, actor, entity_id)
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
            'error': error, 'draft': draft, 'show_assistant_dock': False,
        }, status_code=status_code, headers={'Cache-Control': 'no-store'})

    @app.get('/matters/{slug}/entities', response_class=HTMLResponse)
    @app.get('/matters/{slug}/entities/{entity_id}', response_class=HTMLResponse)
    def entities(request: Request, slug: str, entity_id: str = '',
                 q: str = Query('', max_length=200), page: int = Query(1, ge=1, le=100_000),
                 support: str = Query('', max_length=40), return_to: str = Query('', max_length=4000)):
        return render(request, slug, entity_id=entity_id, q=q, page=page, support=support, return_to=return_to)

    @app.post('/matters/{slug}/entities/actions', dependencies=[Depends(require_csrf)])
    def entity_action(request: Request, slug: str, action: str = Form(..., max_length=24),
                      entity_id: str = Form('', max_length=80), expected_revision: int = Form(0, ge=0),
                      display_name: str = Form('', max_length=160), entity_type: str = Form('person', max_length=24),
                      status: str = Form('needs_review', max_length=24), aliases: str = Form('', max_length=5000),
                      support: str = Form('', max_length=40), item_id: str = Form('', max_length=80),
                      mention_id: str = Form('', max_length=80), q: str = Form('', max_length=200),
                      return_to: str = Form('', max_length=4000)):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        service = service_for(matter)
        fields = dict(display_name=display_name, entity_type=entity_type, status=status, aliases=aliases)
        deleted_entity_id = ''
        try:
            if action == 'create':
                entity = service.create(matter.matter_id, actor, support=support, **fields)
                entity_id = entity['entity_id']
            elif action == 'update':
                service.update(matter.matter_id, actor, entity_id, expected_revision=expected_revision, **fields)
            elif action == 'attach':
                service.attach(matter.matter_id, actor, entity_id, expected_revision=expected_revision, support=support)
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
                              error=error, draft=dict(fields, action=action),
                              status_code=409 if isinstance(exc, (EntityEditConflict, KeyError)) else 400)
            except HTTPException as gone:
                if gone.status_code != 404:
                    raise
                return render(request, slug, q=q, support=support, return_to=return_to,
                              error=error, draft=dict(fields, action='create'), status_code=409)
        audit(request, 'entity.' + action, 'success', context=auth_context(request), matter=matter,
              object_type='entity', object_id=entity_id or deleted_entity_id or matter.matter_id)
        path = f'/matters/{slug}/entities' + ('/' + entity_id if entity_id else '')
        return RedirectResponse(path + '?' + urlencode(dict(q=q, return_to=return_path(slug, return_to))), status_code=303)

    @app.get('/matters/{slug}/entities/{entity_id}/export', dependencies=[Depends(require_response_lease)])
    def entity_export(request: Request, slug: str, entity_id: str):
        matter = authorized_matter(request, slug)
        try:
            entity, mentions, history, note = service_for(matter).detail(matter.matter_id, auth_context(request).principal_id, entity_id)
        except KeyError as exc:
            raise HTTPException(404, 'Entity not found') from exc
        payload = dict(format='recordbench-entity-v1', entity=entity, mentions=mentions, history=history)
        audit(request, 'entity.export', 'success', context=auth_context(request), matter=matter,
              object_type='entity', object_id=entity_id)
        return transfer_response_lease(request, Response(json.dumps(payload, indent=2), media_type='application/json', headers={
            'Content-Disposition': 'attachment; filename="entity.json"', 'Cache-Control': 'no-store'}))
