"""Resource-bounded native DOCX extraction for exact section support."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_DOCX_SECTIONS = 5_000
MAX_DOCX_SECTION_CHARS = 50_000
MAX_DOCX_TOTAL_CHARS = 5_000_000
DOCX_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class DocxSection:
    section_number: int
    text: str


def extract_docx_sections(path: Path) -> tuple[DocxSection, ...]:
    """Extract ordered DOCX sections in a short-lived bounded child process."""
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise ValueError("DOCX source must be a regular, non-symlink file")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("docx_extract_helper.py")), str(source)],
            capture_output=True,
            check=False,
            timeout=DOCX_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("DOCX extraction timed out") from exc
    if len(completed.stdout) > 16 * 1024 * 1024:
        raise ValueError("DOCX extraction output exceeded its limit")
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("DOCX could not be extracted") from exc
    error = payload.get("error")
    if error in {"entry_limit", "expanded_size_limit", "section_limit", "text_limit"}:
        raise ValueError("That DOCX exceeds the extraction limits.")
    if completed.returncode != 0 or error:
        raise ValueError("That DOCX is damaged or malformed.")
    sections = payload.get("sections")
    if not isinstance(sections, list) or len(sections) > MAX_DOCX_SECTIONS:
        raise ValueError("DOCX extraction returned invalid output")
    result: list[DocxSection] = []
    total = 0
    for index, item in enumerate(sections, 1):
        if (
            not isinstance(item, dict)
            or item.get("section_number") != index
            or not isinstance(item.get("text"), str)
        ):
            raise ValueError("DOCX extraction returned invalid output")
        text = item["text"]
        if not text or len(text) > MAX_DOCX_SECTION_CHARS:
            raise ValueError("DOCX extraction returned invalid output")
        total += len(text)
        if total > MAX_DOCX_TOTAL_CHARS:
            raise ValueError("That DOCX exceeds the extraction limits.")
        result.append(DocxSection(index, text))
    return tuple(result)
