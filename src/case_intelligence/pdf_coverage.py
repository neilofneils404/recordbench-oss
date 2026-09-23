"""Shared limits for review of current and historical PDF extractions."""

PDF_COVERAGE_NOTICE = (
    "PDF search and review use extracted text only. Searchable pages do not prove "
    "complete extraction: image text can be missed, and OCR can be skipped, "
    "partial, timed out, or capped. Check the extraction status and original "
    "pages; no match or a finished text review does not establish complete PDF "
    "coverage. Older extractions may have no recorded OCR coverage."
)

PDF_SAVED_RESULT_NOTICE = (
    "PDF extraction completeness is unknown for this saved result. This matter "
    "contains PDF sources; a saved complete status does not establish that all "
    "original PDF content was extracted or searched. This viewing/export note "
    "leaves the saved coverage receipt and citations unchanged."
)
