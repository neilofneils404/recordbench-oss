"""Synthetic regressions for bounded OCR outcomes and preserved native text."""
import io
import subprocess
from types import SimpleNamespace

import pytest

from case_intelligence import pilot_uploads
from case_intelligence.pilot_uploads import PdfOcrResult, PilotStore
from case_intelligence.review_bench_v2 import PdfPage
from case_intelligence.exact_search_results import search_documents


def ingest(tmp_path, monkeypatch, pages, recognize, *, mode="expanded", limit="500"):
    monkeypatch.setenv("CASE_INTELLIGENCE_OCR_MODE", mode)
    monkeypatch.setenv("CASE_INTELLIGENCE_MAX_OCR_PAGES", limit)
    monkeypatch.setattr("case_intelligence.review_bench_v2.extract_pdf_pages", lambda _: pages)
    monkeypatch.setattr(pilot_uploads, "_ocr_pdf_page", recognize)
    store = PilotStore(tmp_path / "store")
    document, _ = store.store_stream("synthetic.pdf", "application/pdf", io.BytesIO(b"%PDF-synthetic-outcomes"))
    return store, document


def test_shorter_ocr_adds_body_without_losing_long_native_stamp(tmp_path, monkeypatch):
    native = "Synthetic exhibit stamp received by the fictional review desk reference STAMPONLY"
    _, document = ingest(tmp_path, monkeypatch, [PdfPage(1, native, 0.8, True)],
                         lambda *_: PdfOcrResult("BODYONLY", "recognized"))
    text = document.parsed_units()[0].text
    assert text == native + "\n\nBODYONLY"
    for term in ("STAMPONLY", "BODYONLY"):
        result = search_documents([document], term, scope=("synthetic", "", ""))
        assert result.total == 1
        assert result.items[0].document_id == document.document_id
    assert "Complete page reading is not established" in document.message


def test_good_existing_text_does_not_duplicate_ocr(tmp_path, monkeypatch):
    native = "Synthetic orchard evidence\nSecond native line."
    _, document = ingest(tmp_path, monkeypatch, [PdfPage(1, native, 1.0, True)],
                         lambda *_: PdfOcrResult("Synthetic orchard evidence\nSecond native line.", "recognized"))
    assert document.parsed_units()[0].text == native


@pytest.mark.parametrize("status,notice", [
    ("timed_out", "OCR timed out: 1"),
    ("failed", "OCR failed: 1"),
    ("no_text", "OCR returned no text: 1"),
    ("output_limit", "OCR text/raster limit reached: 1"),
])
def test_failed_ocr_retains_native_text_and_durable_outcome(tmp_path, monkeypatch, status, notice):
    native = "Long synthetic stamp that must survive STAMPONLY"
    store, document = ingest(tmp_path, monkeypatch, [PdfPage(1, native, 0.8, True)],
                              lambda *_: PdfOcrResult(status=status))
    assert document.state == "ready"
    assert document.parsed_units()[0].text == native
    assert notice in document.message
    assert "OCR attempted on 1" in document.message
    restarted = PilotStore(store.root).get(document.document_id)
    assert restarted.message == document.message
    assert restarted.parsed_units() == document.parsed_units()
    assert restarted.version_id == document.version_id
    assert restarted.digest == document.digest


def test_cap_and_disabled_are_skipped_not_unreadable_after_ocr(tmp_path, monkeypatch):
    pages = [PdfPage(n, "Long synthetic stamp of received exhibit", 0.9, True) for n in range(1, 4)]
    calls = []
    _, doc = ingest(tmp_path, monkeypatch, pages,
                    lambda _, n: calls.append(n) or PdfOcrResult("body", "recognized"), limit="1")
    assert calls == [1]
    assert "OCR skipped (page limit): 2" in doc.message
    assert "unreadable after OCR" not in doc.message
    assert doc.page_count == 3


@pytest.mark.parametrize("mode,notice", [("off", "disabled"), ("selective", "selective mode")])
def test_disabled_and_selective_stamped_scans_report_skipped(tmp_path, monkeypatch, mode, notice):
    def unexpected(*_):
        raise AssertionError("OCR should not run")
    _, doc = ingest(tmp_path, monkeypatch, [PdfPage(1, "Long synthetic stamped text only", 0.8, True)],
                    unexpected, mode=mode)
    assert f"OCR skipped ({notice}): 1" in doc.message
    assert "OCR attempted on 0" in doc.message


def test_combined_text_budget_retains_native_and_records_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot_uploads, "MAX_PDF_TOTAL_CHARS", 60)
    native = "Native synthetic evidence " * 2
    _, doc = ingest(tmp_path, monkeypatch, [PdfPage(1, native, 1.0, True)],
                    lambda *_: PdfOcrResult("This OCR output would exceed the total budget.", "recognized"))
    assert doc.parsed_units()[0].text == native.strip()
    assert "OCR text/raster limit reached: 1" in doc.message


def test_empty_timed_out_pages_keep_total_and_reason(tmp_path, monkeypatch):
    _, doc = ingest(tmp_path, monkeypatch, [PdfPage(1, "", 1.0, True), PdfPage(2, "", 1.0, True)],
                    lambda *_: PdfOcrResult(status="timed_out"), limit="1")
    assert doc.state == "needs_ocr" and doc.page_count == 2
    assert "0 of 2 pages with searchable text" in doc.message
    assert "OCR timed out: 1" in doc.message
    assert "OCR skipped (page limit): 1" in doc.message


def test_ocr_subprocess_timeout_is_distinguished(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 20)
    monkeypatch.setattr(pilot_uploads.subprocess, "run", timeout)
    assert pilot_uploads._ocr_pdf_page(tmp_path / "synthetic.pdf", 1).status == "timed_out"


def test_ocr_uses_first_layout_result_not_longest(monkeypatch, tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"raster" if len(calls) == 1 else b"short body")
    monkeypatch.setattr(pilot_uploads.subprocess, "run", run)
    result = pilot_uploads._ocr_pdf_page(tmp_path / "synthetic.pdf", 1)
    assert result == PdfOcrResult("short body", "recognized")
    assert len(calls) == 2 and calls[1][-1] == "1"


def test_ready_pdf_reextraction_requires_new_source_identity(tmp_path, monkeypatch):
    store, old = ingest(tmp_path, monkeypatch,
        [PdfPage(1, "Historical synthetic stamp with adequate native text", 1.0, True)],
        lambda *_: PdfOcrResult("newbody", "recognized"), mode="off")
    original = old.document_id, old.version_id, old.digest, old.parsed_units(), old.message
    monkeypatch.setenv("CASE_INTELLIGENCE_OCR_MODE", "expanded")
    with pytest.raises(pilot_uploads.UploadProblem, match="cannot be retried"):
        store.retry(old.document_id)
    new, _ = store.store_stream("synthetic-new-extraction.pdf", "application/pdf",
                                io.BytesIO(b"%PDF-synthetic-outcomes"))
    assert new.document_id != old.document_id and new.version_id != old.version_id
    assert new.digest == old.digest
    assert "newbody" in new.parsed_units()[0].text
    assert original == (old.document_id, old.version_id, old.digest, old.parsed_units(), old.message)
