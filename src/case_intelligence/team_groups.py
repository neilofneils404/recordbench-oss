"""Application-managed reusable groups, separate from provider admission groups."""
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .workspace_store import WorkspaceProblem


def register_team_group_routes(app, *, identity, bench, templates, auth_context,
                               base_context, require_csrf, authorized_matter, audit):
    store = bench.workspace

    def administrator(request):
        context = auth_context(request)
        if not context.is_administrator:
            audit(request, "team_group.manage", "denied", context=context)
            raise HTTPException(403, "Administrator access is required.")
        return context

    def attribution(request, context):
        return {"administrator_override": context.is_administrator,
                "session_id": context.session.session_id if context.session else None,
                "request_id": request.state.request_id}

    def mutation(request, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError as exc:
            audit(request, "team_group.change", "denied")
            raise HTTPException(404, "Group, matter, or person not found.") from exc
        except WorkspaceProblem as exc:
            audit(request, "team_group.change", "denied")
            raise HTTPException(403, str(exc)) from exc

    @app.get("/admin/groups", include_in_schema=False)
    def groups_page(request: Request):
        administrator(request)
        return templates.TemplateResponse(request=request, name="workbench_team_groups.html", context={
            **base_context(request), "team_groups": store.team_groups(),
            "group_members": {g["group_id"]: store.team_group_members(g["group_id"]) for g in store.team_groups()},
            "group_candidates": identity.membership_candidates(),
            "enabled_principals": {p.principal_id for p in identity.membership_candidates()},
        }, headers={"Cache-Control": "no-store"})

    @app.post("/admin/groups", dependencies=[Depends(require_csrf)])
    def create_group(request: Request, name: str = Form(..., max_length=100)):
        context = administrator(request)
        mutation(request, store.create_team_group, name, context.principal_id, **attribution(request, context))
        return RedirectResponse("/admin/groups", status_code=303)

    @app.post("/admin/groups/{group_id}/members", dependencies=[Depends(require_csrf)])
    def add_group_member(request: Request, group_id: str, principal_id: str = Form(..., max_length=100)):
        context = administrator(request)
        if principal_id not in {p.principal_id for p in identity.membership_candidates()}:
            audit(request, "team_group.change", "denied", context=context)
            raise HTTPException(403, "That identity cannot be added.")
        mutation(request, store.set_team_group_member, group_id, principal_id, context.principal_id,
                 present=True, **attribution(request, context))
        return RedirectResponse("/admin/groups", status_code=303)

    @app.post("/admin/groups/{group_id}/members/{principal_id}/remove", dependencies=[Depends(require_csrf)])
    def remove_group_member(request: Request, group_id: str, principal_id: str):
        context = administrator(request)
        mutation(request, store.set_team_group_member, group_id, principal_id, context.principal_id,
                 present=False, **attribution(request, context))
        return RedirectResponse("/admin/groups", status_code=303)

    @app.post("/matters/{slug}/groups", dependencies=[Depends(require_csrf)])
    def grant_group(request: Request, slug: str, group_id: str = Form(..., max_length=100)):
        matter = authorized_matter(request, slug, allow_administrator_write=True)
        context = auth_context(request)
        mutation(request, store.set_matter_group_grant, matter.matter_id, group_id, context.principal_id,
                 present=True, **attribution(request, context))
        return RedirectResponse(f"/matters/{slug}/setup", status_code=303)

    @app.post("/matters/{slug}/groups/{group_id}/remove", dependencies=[Depends(require_csrf)])
    def revoke_group(request: Request, slug: str, group_id: str):
        matter = authorized_matter(request, slug, allow_administrator_write=True)
        context = auth_context(request)
        mutation(request, store.set_matter_group_grant, matter.matter_id, group_id, context.principal_id,
                 present=False, **attribution(request, context))
        return RedirectResponse(f"/matters/{slug}/setup", status_code=303)
