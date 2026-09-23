# PDF OCR selection and extraction coverage

PDF search covers the text that extraction retained. A searchable page does not
establish that all visible page content was read. This applies to older PDFs too;
opening a source or restarting the application never replaces its saved text.

## New ingestion

Native extraction remains in the bounded child process (500 pages, 250,000
characters per page, 5 million total characters, 10 CPU seconds and 15 seconds
wall time). That process also inspects image placements without decoding image
pixels. It sums image bounding boxes clipped to the page CropBox, including inline
images and nested Form objects. Overlap, skew and nonrectangular clipping can
cause overestimation. The traversal stops at 50,000 operations, 256 image
placements, 64 Forms, depth 8 or graphics stack depth 64; unsupported or exhausted
inspection records unknown evidence.
Named pattern colors and Type3 fonts also record unknown evidence because their
paint procedures can contain images outside the inspected page/Form paths.

Expanded OCR selects a page when it has fewer than 20 native alphanumeric
characters, images cover at least 10 percent of the page, or image evidence is
unknown. A long stamp therefore cannot suppress recognition of a large scanned
body. Small logos with useful native text do not ordinarily trigger OCR. These
are selection heuristics, not proofs that native text or recognized text is
complete or accurate. A substantial image with an existing text layer can still
be selected; native text always survives.

Selective mode retains its empty-text-page policy and 25-page cap. Expanded mode
uses the configured `CASE_INTELLIGENCE_MAX_OCR_PAGES`, clamped to 1–500. Disabled
OCR, selective-policy skips and page-cap skips are reported separately from
attempts. Rendering remains limited to a 2,600-pixel longest side and 16 MiB;
rendering and each recognition subprocess have a 20-second timeout. Automatic
orientation/layout recognition is tried first, with a block-layout fallback only when it
returns no alphanumeric text. Longer OCR is never used as a quality score.

Useful native text is retained verbatim as extracted. Distinct OCR lines are
appended on the same original page; whitespace/case-equivalent lines already
present are omitted. This does not reconcile near duplicates or resolve OCR
errors. Combined text shares the native page and document character budgets.
An OCR addition exceeding either budget is omitted with a limit notice, while
native text remains searchable. Page locators and original file bytes/digests
are unchanged.

## Coverage and recovery

Each newly extracted PDF's existing source status records searchable-page and
native-text counts, OCR attempts and returned text, disabled/selective/capped
skips, timeouts, failures, empty results and output limits. A returned-text count
means the tool produced text, not that the page was fully or correctly read.
Blank pages can produce empty OCR; that outcome alone cannot distinguish an
intentional blank from an unreadable scan.

Sources and the source viewer retain this status. Catalog-based PDF coverage
notices conservatively cover every catalog PDF, including historical sources,
and reach readiness, exact searches including zero results, questions,
investigations and their exports. Full-text review analyzes retained text.
When PDFs participated, original-content completeness remains unknown even when
every extracted range was processed. Answer coverage is partial even with zero
excluded files;
full-text analysis-gap counters still describe retained-text work, with an
additional original-PDF completeness caution. Review the original PDF before
relying on missing terms.

There is no new schema, source registry field or automatic backfill. Historical
PDFs receive a conservative coverage notice without fabricated OCR outcomes or
changed extraction/citation identity. Ready sources cannot be retried in place.
Historical answer and investigation views, and answer, investigation and Report
exports, receive a separate conditional PDF caveat. It survives removal of the
last PDF because the current catalog cannot establish historical absence of PDFs.
Their original
coverage receipts and citations remain unchanged, including a historical saved
complete status.
To obtain new extraction for an already-ready PDF, explicitly ingest it as a new
source (for example under a distinct name); existing references keep their old
source basis. Existing failed/no-text recovery still uses the explicit retry
operation, and source-byte verification remains mandatory.

## Regression evidence

The generated synthetic image-PDF suite exercises real ingestion, CPU OCR and
exact phrase search for long/short stamps, image-only pages, pattern-painted
images, native text, small logos, mixed regions/pages and existing text layers.
Blank-page exclusions and
rotated-page selection, native preservation and coverage cautions are also
checked, along with original bytes, digest, source version, page locators and
restart behavior. Outcome tests
separately inject timeouts, failures and resource caps to verify their reporting;
those tests are not recognition-quality evidence.

The real OCR suite requires the production Linux executable paths. Mac probes
with substituted local tool paths or relaxed unsupported resource limits are
portability diagnostics only. Final-head hosted Linux CI and separate supported
installation acceptance remain distinct. No synthetic OCR result establishes
model quality, exhaustive document reading, or hardware readiness.

In the local Mac real-tool probe, the upside-down synthetic body was selected,
but automatic orientation declined to rotate it and returned incorrect text.
Its native stamp survived and the coverage caution remained visible. Recovery
of arbitrary rotated scans is not established by this correction; inspect the
original when recognition is poor, even when OCR returned nonempty text.
