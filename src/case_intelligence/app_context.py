"""Shared application helpers, moved without behavioral changes."""
from __future__ import annotations


def present_value(value):
    if not isinstance(value, str):
        return value
    projected = presentation_text(value)
    # Preserve Jinja's escaping boundary for already-escaped markup.
    return Markup(projected) if isinstance(value, Markup) else projected


def auth_context(request: Request) -> AuthContext:
    context = getattr(request.state, "auth", None)
    if not isinstance(context, AuthContext):
        raise HTTPException(401, "Sign in is required.")
    return context


def requested_path(request: Request) -> str:
    value = request.url.path
    if request.url.query:
        value += "?" + request.url.query
    return IdentityService.safe_next(value)
