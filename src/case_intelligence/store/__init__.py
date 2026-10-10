"""Shared control-store validation constants."""

import re

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{15,80}$")
_SOURCE_DOCUMENT = re.compile(r"^(?:[0-9a-f]{32}|[a-z][a-z0-9-]{15,80})$")
_NOTEBOOK_ITEM = re.compile(r"^notebook-item-[0-9a-f]{32}$")
NOTEBOOK_TYPES = ("fact", "issue", "person", "place", "date", "event", "note")
NOTEBOOK_STATUSES = ("suggested", "confirmed", "disputed", "needs_review", "dismissed")
NOTEBOOK_ORIGINS = ("manual", "answer", "citation", "extraction")
