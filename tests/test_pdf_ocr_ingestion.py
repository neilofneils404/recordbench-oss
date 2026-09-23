"""Synthetic image PDFs through the actual upload, OCR and exact-search path.

All fixture words, pages and pixels are generated here.  Helvetica is a PDF
base font resolved by Poppler at test time; no external document or font asset
is committed.  These integration tests use the production Linux executables.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import subprocess
import sys

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
)

from case_intelligence import pilot_uploads
from case_intelligence.exact_search_results import search_documents
from case_intelligence.pilot_uploads import PilotStore


_PDFTOPPM = Path("/usr/bin/pdftoppm")
_REAL_OCR = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Real PDF OCR integration requires Linux /usr/bin/pdftoppm and /usr/bin/tesseract",
)
_BODY_LINES = (
    "SYNTHETIC OCR REGRESSION RECORD",
    "The {phrase} appears in this scanned body.",
    "A second sentence provides ordinary readable context.",
    "This generated page contains no real source material.",
)


def _native_text(writer, page, lines, *, top=660, size=18, invisible=False):
    """Append PDF text using only the standard Helvetica base font."""
    resources = page.setdefault(NameObject("/Resources"), DictionaryObject())
    fonts = resources.setdefault(NameObject("/Font"), DictionaryObject())
    fonts[NameObject("/F1")] = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    commands = []
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        render_mode = 3 if invisible else 0
        commands.append(f"BT /F1 {size} Tf {render_mode} Tr 45 {top - index * 35} Td ({escaped}) Tj ET")
    stream = DecodedStreamObject()
    existing = page.get_contents()
    stream.set_data((existing.get_data() + b"\n" if existing is not None else b"") + "\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _pdf_bytes(writer):
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _raster_body(tmp_path, phrase, *, pdftoppm=_PDFTOPPM):
    """Render synthetic native text once, then return its raw grayscale pixels."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    _native_text(writer, page, [line.format(phrase=phrase) for line in _BODY_LINES], size=17)
    source = tmp_path / "synthetic-raster-input.pdf"
    source.write_bytes(_pdf_bytes(writer))
    rendered = subprocess.run(
        [str(pdftoppm), "-scale-to", "1800", "-gray", "-singlefile", str(source)],
        capture_output=True, check=True, timeout=20,
    ).stdout
    header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", rendered)
    assert header is not None, "Poppler must produce binary 8-bit grayscale PGM"
    width, height = (int(value) for value in header.groups())
    pixels = rendered[header.end():]
    assert width > 1000 and height > 1000
    assert len(pixels) == width * height
    return width, height, pixels


def _image(writer, page, raster, *, width=612, height=792, left=0, bottom=0):
    image_width, image_height, pixels = raster
    image = DecodedStreamObject()
    image.set_data(pixels)
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(image_width),
        NameObject("/Height"): NumberObject(image_height),
        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    resources = page.setdefault(NameObject("/Resources"), DictionaryObject())
    resources[NameObject("/XObject")] = DictionaryObject({
        NameObject("/Im0"): writer._add_object(image.flate_encode()),
    })
    stream = DecodedStreamObject()
    stream.set_data(f"q {width} 0 0 {height} {left} {bottom} cm /Im0 Do Q".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def synthetic_image_pdf(tmp_path, pages, *, pdftoppm=_PDFTOPPM):
    """Build final image/native pages; images contain no PDF text operators.

    The optional renderer argument is for an explicit external portability
    probe.  The committed integration tests always use production Linux paths.
    """
    writer = PdfWriter()
    for specification in pages:
        page = writer.add_blank_page(width=612, height=792)
        phrase = specification.get("image")
        if phrase:
            _image(
                writer, page, _raster_body(tmp_path, phrase, pdftoppm=pdftoppm),
                width=specification.get("image_width", 612),
                height=specification.get("image_height", 792),
                left=specification.get("image_left", 0),
                bottom=specification.get("image_bottom", 0),
            )
        elif specification.get("logo"):
            _image(writer, page, (16, 16, b"\x00" * 256), width=28, height=28, left=545, bottom=735)
        if specification.get("native"):
            _native_text(
                writer, page, specification["native"],
                top=specification.get("top", 755), size=specification.get("size", 12),
                invisible=specification.get("invisible", False),
            )
        if specification.get("rotation"):
            page.rotate(specification["rotation"])
    return _pdf_bytes(writer)


def _ingest(tmp_path, monkeypatch, payload, *, mode="expanded"):
    monkeypatch.setenv("CASE_INTELLIGENCE_OCR_MODE", mode)
    monkeypatch.setenv("CASE_INTELLIGENCE_OCR_LANGUAGE", "eng")
    store = PilotStore(tmp_path / "synthetic-store")
    document, _ = store.store_stream("Synthetic OCR matrix.pdf", "application/pdf", io.BytesIO(payload))
    return store, document


def _assert_phrase(document, phrase, page):
    result = search_documents([document], f'"{phrase}"', scope=("synthetic-ocr",))
    assert result.total == 1, f"Missing exact phrase {phrase!r} on page {page}: {document.message}"
    assert result.items[0].document_id == document.document_id
    assert result.items[0].source_version == document.version_id
    assert {unit.number for unit in result.items[0].passages} == {page}
    assert {unit.location for unit in result.items[0].passages} == {f"Page {page}"}


@_REAL_OCR
@pytest.mark.parametrize("stamp", [
    ["SHORT STAMP"],
    ["SYNTHETIC LONG INTAKE STAMP WITH MANY NATIVE CHARACTERS", "REGISTERED FOR SYNTHETIC REVIEW ONLY"],
])
def test_stamped_scan_ingest_recovers_image_body_and_preserves_native_stamp(tmp_path, monkeypatch, stamp):
    payload = synthetic_image_pdf(tmp_path, [{"image": "cobalt meadow", "native": stamp}])
    # Prove that the searchable body exists only as pixels before ingestion.
    native = PdfReader(io.BytesIO(payload)).pages[0].extract_text()
    assert "cobalt meadow" not in native
    assert stamp[0] in native
    store, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "cobalt meadow", 1)
    _assert_phrase(document, stamp[0], 1)
    assert document.digest == hashlib.sha256(payload).hexdigest()
    assert (store.files / document.stored_name).read_bytes() == payload


@_REAL_OCR
def test_image_only_pdf_ingests_to_exact_search_with_original_page_locator(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [{"image": "amber orchard"}])
    assert not PdfReader(io.BytesIO(payload)).pages[0].extract_text()
    _, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "amber orchard", 1)


@_REAL_OCR
@pytest.mark.parametrize("logo", [False, True])
def test_native_text_and_small_logo_do_not_trigger_ocr(tmp_path, monkeypatch, logo):
    payload = synthetic_image_pdf(tmp_path, [{
        "native": ["The violet compass is preserved as native text with enough ordinary context."],
        "logo": logo,
    }])
    calls = []
    actual = pilot_uploads._ocr_pdf_page

    def record_call(*args, **kwargs):
        calls.append(args[1])
        return actual(*args, **kwargs)

    monkeypatch.setattr(pilot_uploads, "_ocr_pdf_page", record_call)
    _, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "violet compass", 1)
    assert calls == []


@_REAL_OCR
def test_mixed_pdf_exact_search_and_restart_preserve_source_and_version(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [
        {"native": ["The violet compass belongs to the native first page with readable context."]},
        {"image": "silver lantern", "native": ["SYNTHETIC LONG STAMP FOR THE SECOND PAGE OF THIS RECORD"]},
    ])
    store, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "violet compass", 1)
    _assert_phrase(document, "silver lantern", 2)
    original = (document.digest, document.version_id, document.parsed_units(), document.message)

    def unexpected_ocr(*args, **kwargs):
        pytest.fail("Restart must not silently reprocess an existing source version")

    monkeypatch.setattr(pilot_uploads, "_ocr_pdf_page", unexpected_ocr)
    restarted = PilotStore(store.root)
    current = restarted.get(document.document_id)
    assert current is not None
    assert (current.digest, current.version_id, current.parsed_units(), current.message) == original
    assert current.page_count == 2
    assert (restarted.files / current.stored_name).read_bytes() == payload
    _assert_phrase(current, "silver lantern", 2)


@_REAL_OCR
def test_mixed_native_and_image_regions_both_reach_exact_search(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [{
        "image": "teal waterfall", "image_height": 500,
        "native": [
            "The violet compass remains useful native text in the upper page region.",
            "This generated paragraph belongs to the same page as the scanned body.",
        ],
        "top": 740,
    }])
    _, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "violet compass", 1)
    _assert_phrase(document, "teal waterfall", 1)


@_REAL_OCR
def test_blank_page_keeps_partial_pdf_out_of_complete_exact_search(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [
        {"native": ["The violet compass belongs to the first synthetic page."]},
        {},
    ])
    _, document = _ingest(tmp_path, monkeypatch, payload)
    assert "violet compass" in document.parsed_units()[0].text
    assert document.page_count == 2
    result = search_documents([document], '"violet compass"', scope=("synthetic-ocr",))
    assert result.total == 0
    assert result.exclusions == {"Incomplete page coverage": 1}


@_REAL_OCR
def test_actual_ocr_page_cap_retains_unprocessed_stamp_and_reports_skipped_body(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [
        {"image": "amber orchard", "native": ["SYNTHETIC FIRST PAGE STAMP WITH MANY NATIVE CHARACTERS"]},
        {"image": "cobalt meadow", "native": ["SYNTHETIC SECOND PAGE STAMP WITH MANY NATIVE CHARACTERS"]},
    ])
    monkeypatch.setenv("CASE_INTELLIGENCE_MAX_OCR_PAGES", "1")
    _, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, "amber orchard", 1)
    _assert_phrase(document, "SYNTHETIC SECOND PAGE STAMP", 2)
    assert search_documents([document], '"cobalt meadow"', scope=("synthetic-ocr",)).total == 0
    assert "OCR attempted on 1" in document.message
    assert "OCR skipped (page limit): 1" in document.message
    assert "Complete page reading is not established" in document.message


@_REAL_OCR
def test_enabling_ocr_does_not_silently_reprocess_historical_source_versions(tmp_path, monkeypatch):
    payload = synthetic_image_pdf(tmp_path, [{
        "image": "copper garden",
        "native": ["SYNTHETIC HISTORICAL STAMP WITH MANY NATIVE CHARACTERS"],
    }])
    store, document = _ingest(tmp_path, monkeypatch, payload, mode="off")
    _assert_phrase(document, "SYNTHETIC HISTORICAL STAMP", 1)
    assert search_documents([document], '"copper garden"', scope=("synthetic-ocr",)).total == 0
    original = (document.digest, document.version_id, document.parsed_units(), document.message)
    monkeypatch.setenv("CASE_INTELLIGENCE_OCR_MODE", "expanded")

    def unexpected_ocr(*args, **kwargs):
        pytest.fail("Changing OCR mode must not rewrite a historical extraction or citation basis")

    monkeypatch.setattr(pilot_uploads, "_ocr_pdf_page", unexpected_ocr)
    restarted = PilotStore(store.root)
    current = restarted.get(document.document_id)
    assert (current.digest, current.version_id, current.parsed_units(), current.message) == original
    assert (restarted.files / current.stored_name).read_bytes() == payload
    assert search_documents([current], '"copper garden"', scope=("synthetic-ocr",)).total == 0


@_REAL_OCR
def test_existing_native_ocr_layer_remains_searchable_without_repetition(tmp_path, monkeypatch):
    phrase = "golden harbor"
    body = [line.format(phrase=phrase) for line in _BODY_LINES]
    payload = synthetic_image_pdf(tmp_path, [{
        "image": phrase, "native": body, "top": 660, "size": 17, "invisible": True,
    }])
    _, document = _ingest(tmp_path, monkeypatch, payload)
    _assert_phrase(document, phrase, 1)
    assert document.parsed_units()[0].text.casefold().count(phrase) == 1


@_REAL_OCR
@pytest.mark.parametrize("rotation", [90, 180])
def test_rotated_scan_is_selected_without_claiming_complete_ocr(tmp_path, monkeypatch, rotation):
    payload = synthetic_image_pdf(tmp_path, [{
        "image": "scarlet willow",
        "native": ["SYNTHETIC ROTATED STAMP WITH MANY NATIVE CHARACTERS"],
        "rotation": rotation,
    }])
    store, document = _ingest(tmp_path, monkeypatch, payload)
    # Rotation does not hide the image from selection. Orientation detection
    # can still return garbled text on these real fixtures, so selection or a
    # successful OCR exit must not be presented as complete recognition.
    assert "OCR attempted on 1" in document.message
    assert "Complete page reading is not established" in document.message
    _assert_phrase(document, "SYNTHETIC ROTATED STAMP", 1)
    assert document.digest == hashlib.sha256(payload).hexdigest()
    assert (store.files / document.stored_name).read_bytes() == payload
