"""Read-only HTTP exploration of explicit, source-backed entity roles."""
from urllib.parse import urlencode

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .evidence_graph import EvidenceGraphService
from .review_navigation import matter_return_path
from .workspace_store import WorkspaceProblem


def install_evidence_graph_routes(app, *, assertions_for, authorized_matter,
                                  auth_context, templates, base_context):
    @app.get('/matters/{slug}/connections', response_class=HTMLResponse)
    def connections(request: Request, slug: str,
                    entity_id: str = Query('', max_length=80),
                    page: int = Query(1, ge=1, le=100_000),
                    return_to: str = Query('', max_length=4000)):
        matter = authorized_matter(request, slug)
        actor = auth_context(request).principal_id
        return_to = matter_return_path(slug, return_to, fallback=f'/matters/{slug}/entities')
        if not entity_id:
            return RedirectResponse(f'/matters/{slug}/entities?' + urlencode({'return_to': return_to}),
                                    status_code=303, headers={'Cache-Control': 'no-store'})
        assertions = assertions_for(matter)
        try:
            graph = EvidenceGraphService(assertions).neighborhood(matter.matter_id, actor, entity_id, page=page)
        except KeyError as exc:
            raise HTTPException(404, 'Entity or matter is no longer available') from exc
        except WorkspaceProblem as exc:
            raise HTTPException(400, str(exc)) from exc

        def graph_url(identifier=entity_id, number=page):
            return f'/matters/{slug}/connections?' + urlencode(dict(
                entity_id=identifier, page=number, return_to=return_to))

        if page > graph['pages']:
            try:
                with assertions.repository.transaction(matter.matter_id, actor):
                    pass
            except KeyError as exc:
                raise HTTPException(404, 'Entity or matter is no longer available') from exc
            return RedirectResponse(graph_url(number=graph['pages']), status_code=303,
                                    headers={'Cache-Control': 'no-store'})

        current_url = graph_url()

        def record_url(identifier):
            return f'/matters/{slug}/assertions/{identifier}?' + urlencode({'return_to': current_url})

        def original_url(token):
            return f'/matters/{slug}?' + urlencode(dict(support=token, entity_return_to=current_url)) + '#support-pane'

        def entity_url(identifier):
            return f'/matters/{slug}/entities/{identifier}?' + urlencode({'return_to': current_url})

        def search_url(label):
            # Use the literal-phrase control: a label is never advanced-query code.
            return f'/matters/{slug}/exact-search?' + urlencode(dict(phrase=label, search='true'))

        # The diagram is a compact projection of the evidence list below. Lists
        # retain each admitted role/account and all omission counts.
        graph_height = max(220, len(graph['records']) * 190 + 30)
        for index, entry in enumerate(graph['records']):
            entry['diagram_y'] = index * 190 + 45
            entry['diagram_roles'] = [role for role in entry['roles'] if role['entity_id'] != entity_id][:4]
            entry['diagram_roles_omitted'] = entry['role_total'] - sum(
                role['entity_id'] == entity_id for role in entry['roles']) - len(entry['diagram_roles'])
            entry['center_historical'] = any(role['identity_state'] != 'current'
                for role in entry['roles'] if role['entity_id'] == entity_id)

        response = templates.TemplateResponse(request=request, name='workbench_connections.html', context={
            **base_context(request, matter), 'matter': matter, 'graph': graph,
            'return_to': return_to, 'graph_url': graph_url, 'record_url': record_url,
            'original_url': original_url, 'entity_url': entity_url, 'search_url': search_url,
            'graph_height': graph_height, 'show_assistant_dock': False,
        }, headers={'Cache-Control': 'no-store'})
        # Discard a rendered response if matter access was revoked during work.
        try:
            with assertions.repository.transaction(matter.matter_id, actor):
                pass
        except KeyError as exc:
            raise HTTPException(404, 'Entity or matter is no longer available') from exc
        return response
