"""Read-only first-run guidance derived from existing workspace evidence."""
from __future__ import annotations

from fastapi import HTTPException, Query, Request


def register_onboarding_routes(app, *, identity, bench, templates, auth_context, base_context, audit):
    @app.get("/admin/setup", include_in_schema=False)
    def administrator_setup(request: Request, matter: str = Query("", max_length=80)):
        context = auth_context(request)
        if not context.is_administrator:
            audit(request, "admin.setup", "denied", context=context)
            raise HTTPException(403, "Administrator access is required.")
        # Guide work only in the administrator's existing matter memberships.
        # Workspace oversight does not silently grant write access to a matter.
        matters = bench.matters(context.principal_id)
        selected = next((item for item in matters if item.slug == matter), None) if matter else (matters[0] if matters else None)
        if matter and selected is None:
            raise HTTPException(404, "Choose a matter whose case team you have joined.")
        candidates = {person.principal_id: person for person in identity.membership_candidates()}
        if identity.auth_mode == "local" and identity.local_settings is not None:
            accounts = identity.local_settings.accounts
            candidates = {key: person for key, person in candidates.items()
                          if person.provider_subject in accounts and accounts[person.provider_subject].enabled}
        teammates = tuple(member for member in bench.workspace.members(selected.matter_id)
                          if member.principal_id != context.principal_id and member.principal_id in candidates) if selected else ()
        access_seen = bool(selected and any(bench.workspace.member_access_seen(
            selected.matter_id, member.principal_id, since=member.updated_at) for member in teammates))
        readiness = bench.workspace.matter_readiness(selected.matter_id) if selected else None
        capabilities = bench.capabilities()
        return templates.TemplateResponse(request=request, name="workbench_onboarding.html", context={
            **base_context(request), "setup_matters": matters, "setup_matter": selected,
            "setup_readiness": readiness, "setup_teammates": teammates, "setup_access_seen": access_seen,
            "setup_people_seen": any(key != context.principal_id for key in candidates),
            "setup_capabilities": capabilities,
            "setup_cpu_ready": capabilities.get("storage") == "ready" and capabilities.get("malware_scan") in {"ready", "not required"},
        }, headers={"Cache-Control": "no-store"})
