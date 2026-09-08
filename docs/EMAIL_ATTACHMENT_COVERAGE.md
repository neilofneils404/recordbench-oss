# Email attachment coverage

Status: implemented and locally validated. Final-commit hosted code/security reviews
and the normal merge gate remain required. No runtime activation is implied.

## Outcome and boundaries

Show attachment names/types with an explicit unprocessed-content notice in
newly extracted email headers. Treat attached messages and multipart attachments
as boundaries: their descendant text must not become parent-message body.
Inventory unnamed non-body parts too. Keep container, MIME-part and decoded-body
limits. Attachment child sources, archive expansion and PST support remain
separate work.

Surface the coverage limitation in source review, matter search/answers and
saved answer exports. Email readiness means its extracted text is searchable;
it must not imply complete attachment coverage. Count email sources through the
existing matter-scoped catalog; do not read all source files to display coverage.

## Compatibility and recovery

Preserve existing stored passages and citations. Earlier extraction may contain
attached-message text mixed into parent body, and its attachment inventory may
be incomplete. The notice for existing email must acknowledge incomplete
attachment coverage without claiming that all attachment text is absent. Do not
silently reprocess saved evidence or change its citation basis. Review the
original email and attachments separately when completeness matters; a fresh
upload creates a distinct occurrence processed with the corrected extractor.

No registry fields, source IDs, source versions, schema or dependencies change.
Source rollback retains already saved extraction and its existing
citations. An older reader lacks the new general coverage notices. Saved answers
created before this change retain their historical coverage snapshot.

## Coverage contract

For a matter containing email, `partial_query` is true whenever queries are
otherwise available, even when every received source has searchable text.
`excluded_count` still counts excluded source files and remains zero for a ready
email-only matter. The notice describes the limitation without asserting that
all attachment text is absent from older extractions. It is conservative for
email without attachments, because old source records do not carry a complete
structured attachment inventory. No source-file read or new inventory is added
to readiness queries. Source review also shows the notice before searchable
content; new header units list each attachment boundary, with unknown names
shown as **unnamed**. Descendants of attached messages are not separately listed.

Malformed MIME containers fail as a source-processing error with existing
**Try again** and removal recovery. Correct a damaged original before a fresh
upload. Earlier saved answers keep their historical snapshot; new answers,
including the legacy synchronous path, save current attachment coverage.
Coverage is retained in answer/conversation Markdown and Word exports and the
ordinary matter bundle. This change does not unpack attachments or provide a
new email application; use the original email to review attachments separately.

## Synthetic acceptance

```console
python -m pytest -q tests/test_email_attachment_coverage.py tests/test_answer_jobs.py tests/test_processing_awareness.py tests/test_work_product_exports.py
python scripts/browser-accept-email-coverage.py --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver --output /tmp/generated-email-coverage
python scripts/verify-email-coverage-rollback.py --previous-source /path/to/previous-checkout
make check
```

Six initial failing parser cases reproduced attached-text leakage, missing
inventory/coverage and malformed-container readiness. Nine parser/HTTP tests now
pass; the expanded answer/readiness/export selection passes 39 tests. Fixtures
cover ordinary, unnamed, inline non-body, attached-message and attached-multipart
parts, HTML alternatives, MIME/body limits, exact parent passages, attachment-only
no-match searches, saved coverage and cross-matter access. The stopped-reader
script reproduces the old attached-message extraction, preserves every old
unit/digest/version on upgrade, checks corrected new extraction, reads both with
the older application and exports the saved notice, then verifies forward read
and unchanged original bytes. No new storage contract requires migration.

September 8, 2026 acceptance: `make check` passes 961 application tests with nine
optional skips, all 194 transcription tests, compilation, both Compose graphs and
publication inspection. All six Chrome workflows pass: actual selected-file
upload/receipt/source inventory, desktop/narrow review, attachment-only no-match
search, exact parent support saved to notes, ordinary question submission and
saved answer download/reload, cross-matter denial, final bundle and owner closure
with unchanged external email bytes. Desktop and narrow screenshots were
inspected. The stopped-reader/forward-read drill also resolves the support token
created by the old extractor to the same exact old source version and passage.

Next action: complete final-commit hosted reviews, reconcile findings, satisfy
the normal merge gate and let each deployment perform its own integration and
activation checks. Attachment child-source extraction remains a separate slice.
