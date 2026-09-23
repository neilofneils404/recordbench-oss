"""Synthetic PDF geometry regressions; no OCR engine is mocked by these tests."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
    NumberObject, RectangleObject,
)

from case_intelligence import pdf_extract_helper
from case_intelligence.review_bench_v2 import PdfPage, extract_pdf_pages


def _array(values):
    return ArrayObject([FloatObject(value) for value in values])


def _stream(data):
    stream = DecodedStreamObject()
    stream.set_data(data)
    return stream


def _image():
    image = _stream(bytes([255, 0, 255, 0] * 16))
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(8),
        NameObject("/Height"): NumberObject(8),
        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    return image


def _pdf(path, commands=b"", native="", *, rotation=0, crop=None, form=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): writer._add_object(_image())}),
    })
    if form is not None:
        form[NameObject("/Resources")] = resources
        # Give the form its own resources before adding it to page resources.
        resources = DictionaryObject(dict(resources))
        resources[NameObject("/XObject")] = DictionaryObject(dict(resources["/XObject"]))
        resources["/XObject"][NameObject("/Body")] = writer._add_object(form)
    page[NameObject("/Resources")] = resources
    if native:
        commands += f"\nBT /F1 7 Tf 4 92 Td ({native}) Tj ET\n".encode("ascii")
    page[NameObject("/Contents")] = writer._add_object(_stream(commands))
    if rotation:
        page.rotate(rotation)
    if crop:
        page.cropbox = RectangleObject(crop)
    writer.write(path)


def _read_pages(source):
    reader = PdfReader(source, strict=True)
    return tuple(
        PdfPage(number, (page.extract_text() or "").strip(),
                *pdf_extract_helper.page_image_evidence(page, reader))
        for number, page in enumerate(reader.pages, 1)
    )


@pytest.mark.parametrize(("commands", "native", "expected"), [
    (b"", "A useful native paragraph without painted images.", 0.0),
    (b"q 80 0 0 80 10 10 cm /Scan Do Q", "", 0.64),
    (b"q 80 0 0 80 10 10 cm /Scan Do Q", "STAMP", 0.64),
    (b"q 80 0 0 80 10 10 cm /Scan Do Q", "RECEIVED FOR SYNTHETIC RECORD REVIEW", 0.64),
    (b"q 100 0 0 40 0 0 cm /Scan Do Q", "Native text above an image body.", 0.4),
    (b"q 10 0 0 10 5 5 cm /Scan Do Q", "A useful native paragraph with a small logo.", 0.01),
    (b"q 80 0 0 80 110 110 cm /Scan Do Q", "An off-page image is not a scan body.", 0.0),
    (b"q 0 80 -80 0 90 10 cm /Scan Do Q", "A rotated scan body and native stamp.", 0.64),
])
def test_real_pdf_reports_painted_image_geometry_and_preserves_native_text(tmp_path, commands, native, expected):
    source = tmp_path / "synthetic.pdf"
    _pdf(source, commands, native)
    pages = _read_pages(source)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].text == native
    assert pages[0].image_evidence_known is True
    assert pages[0].image_coverage == pytest.approx(expected)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_cropbox_and_page_rotation_keep_image_fraction(tmp_path, rotation):
    source = tmp_path / "synthetic-rotation.pdf"
    _pdf(source, b"q 50 0 0 50 25 25 cm /Scan Do Q", rotation=rotation, crop=(25, 25, 75, 75))
    page, = _read_pages(source)
    assert page.image_evidence_known is True
    assert page.image_coverage == 1.0


def test_inline_image_is_counted_without_pixel_decoding(tmp_path):
    source = tmp_path / "synthetic-inline.pdf"
    _pdf(source, b"q 80 0 0 80 10 10 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \xff EI Q")
    page, = _read_pages(source)
    assert page.image_evidence_known is True
    assert page.image_coverage == pytest.approx(0.64)


def test_form_image_placement_uses_form_and_parent_matrices_and_bbox(tmp_path):
    source = tmp_path / "synthetic-form.pdf"
    form = _stream(b"/Scan Do")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): _array([0, 0, 1, 1]),
        NameObject("/Matrix"): _array([2, 0, 0, 2, 0, 0]),
    })
    _pdf(source, b"q 40 0 0 40 10 10 cm /Body Do Q", "FORM STAMP", form=form)
    page, = _read_pages(source)
    assert page.text == "FORM STAMP"
    assert page.image_evidence_known is True
    assert page.image_coverage == pytest.approx(0.64)


@pytest.mark.parametrize("limit", ["MAX_IMAGE_EVIDENCE_FORMS", "MAX_IMAGE_EVIDENCE_DEPTH"])
def test_form_traversal_limits_report_unknown(tmp_path, monkeypatch, limit):
    source = tmp_path / "synthetic-bounded-form.pdf"
    form = _stream(b"/Scan Do")
    form.update({NameObject("/Subtype"): NameObject("/Form"),
                 NameObject("/BBox"): _array([0, 0, 1, 1])})
    _pdf(source, b"q 80 0 0 80 10 10 cm /Body Do Q", "RETAIN NATIVE STAMP", form=form)
    monkeypatch.setattr(pdf_extract_helper, limit, 0)
    page, = _read_pages(source)
    assert page.text == "RETAIN NATIVE STAMP"
    assert page.image_evidence_known is False


@pytest.mark.parametrize(("limit", "value", "commands"), [
    ("MAX_IMAGE_EVIDENCE_OPERATIONS", 1, b"q 80 0 0 80 0 0 cm /Scan Do Q"),
    ("MAX_IMAGE_EVIDENCE_PLACEMENTS", 1, b"/Scan Do /Scan Do"),
    ("MAX_IMAGE_EVIDENCE_DEPTH", 0, b"q q /Scan Do Q Q"),
])
def test_bounded_traversal_returns_unknown_instead_of_absence(tmp_path, monkeypatch, limit, value, commands):
    source = tmp_path / "synthetic-bounded.pdf"
    _pdf(source, commands)
    reader = PdfReader(source)
    monkeypatch.setattr(pdf_extract_helper, limit, value)
    coverage, known = pdf_extract_helper.page_image_evidence(reader.pages[0], reader)
    assert 0 <= coverage <= 1
    assert known is False


def test_unresolved_image_resource_preserves_native_text_and_reports_unknown(tmp_path):
    source = tmp_path / "synthetic-unresolved.pdf"
    _pdf(source, b"/Missing Do", "Useful native text remains available.")
    page, = _read_pages(source)
    assert page.text == "Useful native text remains available."
    assert page.image_evidence_known is False


@pytest.mark.parametrize("image_evidence", [
    {}, {"image_coverage": 0.5},
    {"image_coverage": -0.1, "image_evidence_known": True},
    {"image_coverage": 1.1, "image_evidence_known": True},
    {"image_coverage": 10 ** 1000, "image_evidence_known": True},
    {"image_coverage": float("nan"), "image_evidence_known": True},
    {"image_coverage": float("inf"), "image_evidence_known": True},
    {"image_coverage": True, "image_evidence_known": True},
    {"image_coverage": "0.5", "image_evidence_known": True},
    {"image_coverage": 0.5, "image_evidence_known": "true"},
    {"image_coverage": 0.5, "image_evidence_known": 1},
])
def test_child_image_metadata_is_validated_before_use(tmp_path, monkeypatch, image_evidence):
    source = tmp_path / "synthetic-output.pdf"
    source.write_bytes(b"%PDF-synthetic-test")
    payload = {"pages": [{"page_number": 1, "text": "native", **image_evidence}]}
    completed = SimpleNamespace(stdout=json.dumps(payload).encode(), returncode=0)
    monkeypatch.setattr("case_intelligence.review_bench_v2.subprocess.run", lambda *a, **kw: completed)
    with pytest.raises(ValueError, match="invalid image evidence"):
        extract_pdf_pages(source)


def test_old_pdf_page_constructors_explicitly_have_unknown_image_evidence():
    page = PdfPage(1, "Existing caller")
    assert page.image_coverage == 0.0
    assert page.image_evidence_known is False


@pytest.mark.skipif(sys.platform == "darwin", reason="Existing PDF helper RLIMIT_AS requires Linux")
def test_resource_limited_child_transports_native_text_and_image_evidence(tmp_path):
    source = tmp_path / "synthetic-child.pdf"
    _pdf(source, b"q 80 0 0 80 10 10 cm /Scan Do Q", "LONG SYNTHETIC RECEIVED STAMP")
    page, = extract_pdf_pages(source)
    assert page.text == "LONG SYNTHETIC RECEIVED STAMP"
    assert page.image_evidence_known is True
    assert page.image_coverage == pytest.approx(0.64)
