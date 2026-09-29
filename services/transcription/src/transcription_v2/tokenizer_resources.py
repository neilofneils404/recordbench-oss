"""Lightweight checks for the configured offline Punkt language directories."""
from __future__ import annotations

import os
from pathlib import Path
import stat

PUNKT_LANGUAGES = {"en": "english", "es": "spanish"}
PUNKT_FILES = ("collocations.tab", "sent_starters.txt", "abbrev_types.txt", "ortho_context.tab")


def punkt_language_ready(language: str) -> bool:
    """Require all four regular readable files without importing NLTK or ML.

    Inspect only explicit NLTK_DATA roots shared by API and worker. Do not
    substitute machine/user defaults or download absent tokenizer resources.
    The stager verifies archive identity; this is an availability check.
    """
    name = PUNKT_LANGUAGES.get(language)
    if name is None:
        return False
    for value in os.environ.get("NLTK_DATA", "").split(os.pathsep):
        if not value or not Path(value).is_absolute():
            continue
        root = Path(value)
        directory = root / "tokenizers" / "punkt_tab" / name
        try:
            directories = [os.lstat(path) for path in
                           (root, root / "tokenizers", directory.parent, directory)]
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return False
        if not all(stat.S_ISDIR(status.st_mode) for status in directories):
            return False
        try:
            # Match NLTK's first existing language directory: an incomplete
            # earlier directory must not be masked by a later complete one.
            return all(stat.S_ISREG(os.lstat(directory / filename).st_mode)
                       and os.access(directory / filename, os.R_OK)
                       for filename in PUNKT_FILES)
        except (OSError, ValueError):
            return False
    return False
