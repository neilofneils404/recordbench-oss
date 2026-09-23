"""Synthetic DOCX expansion boundaries; use tiny limits instead of large files."""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest

from case_intelligence import work_product_exports as exports


STAMP = "2041-03-12T10:00:00Z"
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _render(blocks, *, title="Synthetic capacity check", created_at=STAMP):
    return exports.blocks_to_docx(blocks, title=title, created_at=created_at)


def _no_paragraph_allocation(_block):
    pytest.fail("Capacity must be checked before allocating paragraph XML/runs.")


@pytest.mark.parametrize("separator", ["\t", "\n", "\r", "\r\n"])
def test_separator_expansion_is_rejected_before_paragraph_allocation(monkeypatch, separator):
    blocks = (exports.ExportBlock(separator * 12),)
    monkeypatch.setattr(exports, "MAX_DOCX_RUNS", 20, raising=False)
    monkeypatch.setattr(exports, "_paragraph_xml", _no_paragraph_allocation)
    with pytest.raises(exports.ExportProblem, match="Word export.*smaller selection or choose Markdown"):
        _render(blocks)
    assert blocks[0].text == separator * 12


def test_run_limit_is_aggregate_across_empty_and_small_blocks(monkeypatch):
    blocks = tuple(exports.ExportBlock("") for _ in range(5))
    monkeypatch.setattr(exports, "MAX_DOCX_RUNS", 4, raising=False)
    monkeypatch.setattr(exports, "_paragraph_xml", _no_paragraph_allocation)
    with pytest.raises(exports.ExportProblem, match="Word export"):
        _render(blocks)


@pytest.mark.parametrize("value", [
    "Ordinary synthetic words", "\tbefore\t\tafter\t", "before\r\nafter\x1b",
    "& <literal> &#13; café العربية 👩\u200d💻", "",
    pytest.param("x" * 16_383 + "\r\n\t&<\ud800👩", id="utf8-chunk-boundary"),
])
def test_exact_xml_and_run_boundaries_preserve_the_accepted_document(monkeypatch, value):
    blocks = (exports.ExportBlock(value, "title"), exports.ExportBlock(value, "unknown-style"))
    title = value + "\r\n\t"
    original = _render(blocks, title=title)
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        xml_bytes = sum(info.file_size for info in archive.infolist())
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        expected_parts = {name: archive.read(name) for name in archive.namelist()}
    run_count = len(document.findall(f".//{WORD}r"))
    monkeypatch.setattr(exports, "MAX_DOCX_XML_BYTES", xml_bytes, raising=False)
    monkeypatch.setattr(exports, "MAX_DOCX_RUNS", run_count, raising=False)
    with zipfile.ZipFile(io.BytesIO(_render(blocks, title=title))) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == expected_parts
    monkeypatch.setattr(exports, "_paragraph_xml", _no_paragraph_allocation)
    monkeypatch.setattr(exports, "MAX_DOCX_XML_BYTES", xml_bytes - 1)
    with pytest.raises(exports.ExportProblem, match="Word export"):
        _render(blocks, title=title)
    monkeypatch.setattr(exports, "MAX_DOCX_XML_BYTES", xml_bytes)
    monkeypatch.setattr(exports, "MAX_DOCX_RUNS", run_count - 1)
    with pytest.raises(exports.ExportProblem, match="Word export"):
        _render(blocks, title=title)
    assert blocks[0].text == blocks[1].text == value


@pytest.mark.parametrize("field", ["title", "created_at"])
def test_metadata_expansion_counts_before_any_body_allocation(monkeypatch, field):
    blocks = (exports.ExportBlock("Unchanged synthetic body"),)
    value = {field: "<&>\r👩" * 20}
    with zipfile.ZipFile(io.BytesIO(_render(blocks, **value))) as archive:
        total = sum(info.file_size for info in archive.infolist())
    monkeypatch.setattr(exports, "MAX_DOCX_XML_BYTES", total - 1, raising=False)
    monkeypatch.setattr(exports, "_paragraph_xml", _no_paragraph_allocation)
    with pytest.raises(exports.ExportProblem, match="Word export"):
        _render(blocks, **value)


def test_plain_text_keeps_existing_character_capacity(monkeypatch):
    monkeypatch.setattr(exports, "MAX_EXPORT_TEXT_CHARS", 128)
    with zipfile.ZipFile(io.BytesIO(_render((exports.ExportBlock("a" * 128),)))) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
    assert "".join(document.itertext()) == "a" * 128
    with pytest.raises(exports.ExportProblem, match="too large"):
        _render((exports.ExportBlock("a" * 129),))
