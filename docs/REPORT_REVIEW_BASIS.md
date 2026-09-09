# Preserve the review behind a Report

Saving an investigation to a Report now creates editable sections for its
question, outcome, recorded evidence passes, gaps, scope/coverage, and method.
The original run ID and result revision remain in the text and section origin.
An unanswerable result is labeled as needing review, not verified synthesis.
Missing historical counters and stop reasons say "Not recorded" rather than
inventing values. No new generation occurs during conversion.

Only support belonging to a section's saved claims/limitation is attached to
that section. The saved summary and pass text are checked against their answer
records, and the exact evidence ledger and nested citations are revalidated
before creation. Stale or inconsistent support returns to the original run with
an error; it does not produce an apparently supported Report.

Every-source Reports separately record the frozen criterion, machine counts,
human review counts, uncertainty, and opposing machine/human inclusion labels.
Counts derive from one retrieved decision population, not independently updated
aggregate metrics. Decision details prioritize disagreements and attention
items, then frozen order. They retain rationale, human notes, reviewer display
name when available, review time, source version, and decision revision.

At most 50 decision details and 100 citation entries are reproduced. The Report
states exactly how many are included and omitted and gives the original ledger
path. The complete ledger export remains necessary for all decision detail.
Neither a frozen source population nor a completed screening run means every
page was analyzed. An incomplete population cannot be summarized as complete.

Conversion inserts the header, sections, and citations in one transaction after
validating every section. A bad later section, failed insert, or revoked matter
membership leaves no partial new Report. Existing Reports and manual edits are
not rewritten. Converted sections use existing editing/conflict guards and
export in individual Word/Markdown downloads and complete matter bundles.

## Validation and compatibility

`tests/test_report_review_basis.py` covers normal/gap/abstention conversion,
exact section support, exports and saved edits, stale sources, interrupted
inserts, membership denial, backup/clean restore, human disagreements, and
explicit detail caps. Existing report-conflict and research suites also apply.

Run the real synthetic browser path with:

```bash
PYTHONPATH=src python scripts/browser-accept-review-report.py \
  --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver \
  --output /path/to/synthetic-results
```

There is no schema or model change. The existing Report records remain readable
by older code; rollback changes future conversion behavior but retains converted
sections. The backup/restore test verifies these sections through a fresh store.
No completeness, model-quality, or deployment qualification follows from this
conversion improvement. Existing Report export-readiness work is separate.
