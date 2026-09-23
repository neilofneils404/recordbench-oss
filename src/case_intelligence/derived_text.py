"""Version 1 presentation policy; never use this to identify source material.

Each unsupported character becomes one space, preserving word boundaries and
character positions. Tabs, line endings and Unicode format characters (including
joiners) remain intact. No NFC, trimming or whitespace collapsing occurs here.
This policy starts after extraction; extractors retain their own line rules.
Source bytes, existing extraction text, digests and locators keep their own basis.
"""
from __future__ import annotations

import re


PRESENTATION_TEXT_POLICY = "controls-to-spaces-v1"
_UNSUPPORTED = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff]")


def presentation_text(value: str) -> str:
    """Project already-bounded text for prose/serialization without expansion."""
    return _UNSUPPORTED.sub(" ", value)
