"""Synthetic malformed shared-string references must not create evidence."""
import io
import zipfile

import pytest

from case_intelligence.extended_extract import extract_xlsx
from case_intelligence.pilot_uploads import PilotStore
from tests.test_review_tools import CleanScanner, _xlsx


def workbook(index):
    output = io.BytesIO()
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(io.BytesIO(_xlsx())) as original, zipfile.ZipFile(output, "w") as archive:
        for name in original.namelist():
            if name != "xl/worksheets/sheet1.xml":
                archive.writestr(name, original.read(name))
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{namespace}">'
                         '<si><t>Synthetic first value</t></si><si><t>Synthetic last value</t></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{namespace}">'
                         f'<sheetData><row r="1"><c r="A1" t="s"><v>{index}</v></c></row>'
                         '</sheetData></worksheet>')
    return output.getvalue()


@pytest.mark.parametrize("index", ["-1", "-2", "", "2", "invalid", "0_1", "\u0661", "\uff11", "\u00a01"])
def test_invalid_shared_index_is_rejected(tmp_path, index):
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(workbook(index))
    with pytest.raises(ValueError, match="invalid shared value"):
        extract_xlsx(path)


@pytest.mark.parametrize("index, expected", [
    ("0", "first"), ("1", "last"), (" +1 ", "last"),
    (" \t+1\r\n", "last"), ("-0", "first"), ("01", "last"),
])
def test_valid_shared_index_preserves_exact_value(tmp_path, index, expected):
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(workbook(index))
    sections = extract_xlsx(path)
    assert len(sections) == 1
    assert sections[0].text == f"Row 1: A1: Synthetic {expected} value"


@pytest.mark.parametrize("index", ["-1", "", "0_1", "\u0661", "\uff11", "\u00a01"])
def test_bad_shared_index_never_becomes_searchable_source_text(tmp_path, index):
    store = PilotStore(tmp_path / "sources", malware_scanner=CleanScanner(), malware_scan_mode="extended")
    document, _ = store.store_stream(
        "synthetic.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        io.BytesIO(workbook(index)), retain_extraction_failure=True)
    assert document.state == "failed"
    assert not document.parsed_units()
    assert "invalid shared value" in document.message
