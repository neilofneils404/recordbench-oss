"""Small authentication boundary for the loopback API.

The service expects a reverse proxy or Transcript Studio to authenticate reviewers. The API
still requires its own bearer token whenever it binds beyond loopback, and it
uses a trusted user header to enforce per-owner job access.
"""

from __future__ import annotations

import hashlib
import hmac
import re


_OWNER_PATTERN = re.compile(r"[^A-Za-z0-9_.@-]+")


class AuthenticationError(PermissionError):
    pass


def authenticate(
    *,
    configured_token: str,
    authorization: str | None,
    claimed_owner: str | None,
) -> str:
    if configured_token:
        scheme, separator, supplied = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.encode("utf-8"), configured_token.encode("utf-8")
        ):
            raise AuthenticationError("Authentication required")
    owner = _OWNER_PATTERN.sub("_", (claimed_owner or "local-reviewer").strip())[:128]
    return owner or "local-reviewer"


def owner_key(owner: str) -> str:
    """Opaque owner key suitable for paths/log fields without exposing identity."""
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
