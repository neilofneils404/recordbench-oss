"""Bounded child process for native OOXML/DOCX text extraction."""
from __future__ import annotations

import json
import resource
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_ENTRIES = 5_000
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_XML_BYTES = 16 * 1024 * 1024
MAX_BLOCKS = 100_000
MAX_SECTION_CHARS = 50_000
MAX_TOTAL_CHARS = 5_000_000
MAX_SECTIONS = 5_000
BLOCKS_PER_SECTION = 12
TARGET_SECTION_CHARS = 8_000
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _limit_process() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    memory = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _tag(name: str) -> str:
    return f"{{{WORD_NS}}}{name}"


def _text(node: ElementTree.Element) -> str:
    pieces: list[str] = []
    for value in node.iter():
        if value.tag == _tag("t") and value.text:
            pieces.append(value.text)
        elif value.tag == _tag("tab"):
            pieces.append("\t")
        elif value.tag in {_tag("br"), _tag("cr")}:
            pieces.append("\n")
    return "".join(pieces).strip()


def _paragraph(node: ElementTree.Element) -> tuple[str, bool]:
    text = _text(node)
    style = node.find(f"./{_tag('pPr')}/{_tag('pStyle')}")
    style_value = "" if style is None else style.attrib.get(_tag("val"), "")
    return text, style_value.casefold().startswith("heading")


def _table(node: ElementTree.Element) -> str:
    rows: list[str] = []
    for row in node.findall(f"./{_tag('tr')}"):
        cells = [" ".join(_text(cell).split()) for cell in row.findall(f"./{_tag('tc')}")]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _sections(document_xml: bytes) -> list[dict[str, object]]:
    root = ElementTree.fromstring(document_xml)
    body = root.find(f"./{_tag('body')}")
    if body is None:
        raise ValueError("body")
    blocks: list[tuple[str, bool]] = []
    for child in body:
        if child.tag == _tag("p"):
            text, heading = _paragraph(child)
        elif child.tag == _tag("tbl"):
            text, heading = _table(child), False
        else:
            continue
        text = text.strip()
        if text:
            blocks.append((text, heading))
            if len(blocks) > MAX_BLOCKS:
                raise OverflowError("block_limit")

    sections: list[str] = []
    current: list[str] = []
    current_chars = 0
    for text, heading in blocks:
        start_new = bool(current) and (
            heading
            or len(current) >= BLOCKS_PER_SECTION
            or current_chars + len(text) + 1 > TARGET_SECTION_CHARS
        )
        if start_new:
            sections.append("\n".join(current))
            current = []
            current_chars = 0
        current.append(text)
        current_chars += len(text) + 1
    if current:
        sections.append("\n".join(current))
    if not sections:
        return []
    if len(sections) > MAX_SECTIONS:
        raise OverflowError("section_limit")
    total = 0
    payload: list[dict[str, object]] = []
    for index, text in enumerate(sections, 1):
        if len(text) > MAX_SECTION_CHARS:
            raise OverflowError("section_limit")
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            raise OverflowError("text_limit")
        payload.append({"section_number": index, "text": text})
    return payload


def main() -> int:
    _limit_process()
    source = Path(sys.argv[1])
    try:
        with source.open("rb") as stream:
            if stream.read(4) != b"PK\x03\x04":
                raise ValueError("signature")
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                print(json.dumps({"error": "entry_limit"}))
                return 2
            if any(info.flag_bits & 1 for info in infos):
                raise ValueError("encrypted")
            expanded = sum(info.file_size for info in infos)
            if expanded > MAX_EXPANDED_BYTES:
                print(json.dumps({"error": "expanded_size_limit"}))
                return 2
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValueError("required_parts")
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCUMENT_XML_BYTES:
                print(json.dumps({"error": "expanded_size_limit"}))
                return 2
            document_xml = archive.read(info)
        print(json.dumps({"sections": _sections(document_xml)}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except OverflowError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except Exception:
        print(json.dumps({"error": "malformed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
