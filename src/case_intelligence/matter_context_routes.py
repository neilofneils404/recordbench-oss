"""Thin HTML selection workflow; proposals remain visible after conflicts."""
import json
from urllib.parse import urlencode

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .matter_context import ContextConflict, MatterContextService
from .review_navigation import matter_return_path
from .workspace_store import WorkspaceProblem


def install_context_routes(app, *, assertions_for, authorized_matter, auth_context, refresh_authority,
                           require_csrf, templates, base_context):
    def render(request, slug, *, kind='', object_id='', return_to='', error='', proposal=None, status_code=200):
        context = auth_context(request)
        matter = authorized_matter(request, slug)
        admin = getattr(request.state, 'administrator_matter_override', None) == matter.matter_id
        actor = matter.owner_id if admin else context.principal_id
        check = lambda: refresh_authority(request, slug, context, admin)
        service = MatterContextService(assertions_for(matter))
        candidate = None
        try:
            selection, candidate = service.inspect(matter.matter_id, actor, kind=kind, object_id=object_id, check_authority=check)
        except (WorkspaceProblem, KeyError) as exc:
            check()
            selection, _ = service.inspect(matter.matter_id, actor, check_authority=check)
            error = error or (str(exc) if isinstance(exc, WorkspaceProblem) else 'Record missing. It cannot be recreated here.')
            status_code = max(status_code, 400)
        back = matter_return_path(slug, return_to, fallback=f'/matters/{slug}/notebook')
        current_url = f'/matters/{slug}/context?' + urlencode(dict(kind=kind, object_id=object_id, return_to=back))
        def inspect_url(entry):
            return f'/matters/{slug}/context?' + urlencode(dict(kind=entry['kind'], object_id=entry['object_id'], return_to=back))
        def record_url(kind, identifier):
            if kind == 'notebook_item':
                return f'/matters/{slug}/notebook?edit={identifier}#{identifier}'
            return f'/matters/{slug}/' + ('entities/' if kind == 'entity' else 'assertions/') + identifier + '?' + urlencode(dict(return_to=current_url))
        response = templates.TemplateResponse(request=request, name='workbench_context.html', context={
            **base_context(request, matter), 'matter': matter, 'selection': selection, 'candidate': candidate,
            'kind': kind, 'object_id': object_id, 'return_to': back, 'error': error, 'proposal': proposal,
            'selected': any(row['kind'] == kind and row['object_id'] == object_id for row in selection['entries']),
            'inspect_url': inspect_url, 'record_url': record_url,
            'source_url': lambda token: f'/matters/{slug}?' + urlencode(dict(support=token, entity_return_to=current_url)) + '#support-pane',
            'show_assistant_dock': False,
        }, status_code=status_code, headers={'Cache-Control': 'no-store'})
        check()
        with service.assertions.repository.transaction(matter.matter_id, actor):
            check()
        return response

    @app.get('/matters/{slug}/context')
    def context_page(request: Request, slug: str, kind: str = Query('', max_length=24),
                     object_id: str = Query('', max_length=80), return_to: str = Query('', max_length=4000)):
        return render(request, slug, kind=kind, object_id=object_id, return_to=return_to)

    @app.post('/matters/{slug}/context', dependencies=[Depends(require_csrf)])
    def context_change(request: Request, slug: str, action: str = Form(..., max_length=16),
                       expected_selection_revision: int = Form(..., ge=0), kind: str = Form('', max_length=24),
                       object_id: str = Form('', max_length=80), approval: str = Form('', max_length=1024),
                       return_to: str = Form('', max_length=4000)):
        context = auth_context(request)
        matter = authorized_matter(request, slug)
        # Visibility through the administrator override never grants mutation.
        check = lambda: refresh_authority(request, slug, context, False)
        check()
        service = MatterContextService(assertions_for(matter))
        proposal = dict(action=action, kind=kind, object_id=object_id,
                        expected_selection_revision=expected_selection_revision, approval=approval)
        try:
            stamp = json.loads(approval) if approval else None
            service.change(matter.matter_id, context.principal_id, expected_revision=expected_selection_revision,
                action=action, kind=kind, object_id=object_id, approval=stamp, check_authority=check)
        except (ValueError, WorkspaceProblem) as exc:
            return render(request, slug, kind=kind, object_id=object_id, return_to=return_to,
                          error=str(exc), proposal=proposal, status_code=409 if isinstance(exc, ContextConflict) else 400)
        except KeyError as exc:
            raise HTTPException(404, 'Matter is no longer available') from exc
        return RedirectResponse(f'/matters/{slug}/context?' + urlencode(dict(return_to=return_to)), status_code=303)
