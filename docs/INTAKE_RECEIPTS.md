# Selected-file receipts

Current contract for the browser's confirmed file and folder selection. This
workspace remains temporary; receipts are deleted with the matter.

## Staff workflow

Choose files or a folder in **Sources**, review the complete selection, and
confirm the ready files. Confirmation first saves a receipt of every selected
item, including unsupported, empty, repeated-path, over-limit and other skipped
items. If nothing can upload, **Save selection receipt** records the selection
without transferring bytes. The preview alone still creates no durable inventory,
upload session or capacity reservation.

**Selected-file receipts** in Sources lists the team's selections; **Older
receipts** reaches earlier pages. Open a receipt to see selected, included,
skipped and unrecorded counts, bytes received, and current availability. Receiving
bytes does not mean parsing, indexing or transcription succeeded. Playable media
without audio remains **Playback only**; held recordings can **Need review**.
A malformed received file remains received and separately shows a failure.

**Open source** opens the exact received source version using the normal viewer,
including its existing integrity and matter checks. A removed or changed version
is unavailable rather than silently pointing at a replacement. Selection reasons
are identified as observations at confirmation. The reviewed selection state and
reason remain separate from the server's filename check, so a capacity-excluded
file still explains the capacity limit even when its filename and size are valid.
The server uses bounded explanations for selection-level exclusions; it does not
store arbitrary browser explanation text as verified output. Empty folders are absent because
the browser supplies files, not a directory inventory.

**Download receipt**, **Text version**, and **Structured version** provide CSV,
Markdown and JSON. The complete matter work-product bundle includes all three
formats for every receipt, including selections consisting entirely of skipped
files. Downloads omit original source bytes and internal identities/locations.
They are work product, not an archive that can reopen the matter.

## Retry and incomplete selections

After interruption, reselect the same files to resume the existing selection and
upload. A lost response can be retried without duplicate receipts, sessions or
byte transfer. Same-page retry also works when browser storage is denied. Without
browser storage, automatic identification of the selection cannot survive closing
or reloading the page; its durable receipt remains discoverable in Sources.

Explicitly cancelling an upload retains its receipt and clears the browser
checkpoint, so a later deliberate selection can start a new attempt.

Metadata is saved in bounded idempotent batches. Until every row is recorded, the
receipt states exactly how many selected files are still unrecorded; uploading
cannot begin. Incomplete exports retain those counts, including a CSV summary
when no file rows were recorded. File names for unrecorded rows cannot be recovered
without reselecting the files.

Older upload checkpoints without a receipt can be adopted only when their exact
manifest and earlier collection batches match the included selection. Previously
received bytes and offsets are retained. A collection already bound to another
receipt cannot be reassigned. Cancelled/missing older checkpoints keep the existing
fresh-retry recovery response. Changed or unauthorized bindings fail without
partial writes or deleting earlier bytes. An explicit session or collection
checkpoint that conflicts with the receipt binding remains a resume mismatch;
receipt idempotency does not silently override it.

The upload route still owns capacity admission, signatures, malware checks and
source processing. A receipt does not authorize a skipped file for upload and
does not reserve storage before a session is created. Metadata retries retain
original row identities and descriptor digests; the uploaded source version is
captured when finalization commits. During adoption, an existing immutable uploaded
source can supply its version from the matter catalog; absent support remains
unavailable.

## API and storage contract

All routes require current matter access. Metadata mutations require CSRF and
the principal who created the receipt; team members can read it. Existing audited
administrator review also opens status, pages and downloads without allowing
receipt mutations or granting an ordinary nonmember access. Export uses the
normal matter response lease and authorized final-export boundary.

| Route | Purpose |
| --- | --- |
| `POST /matters/{slug}/intake-receipts` | Create or return the actor's exact confirmed selection key. |
| `POST /matters/{slug}/intake-receipts/{receipt}/items` | Append or verify a batch of selection rows. |
| `POST /matters/{slug}/intake-receipts/{receipt}/seal` | Verify complete contiguous inventory and included-path uniqueness before transfer. |
| `GET /matters/{slug}/intake-receipts/{receipt}` | Return current selection, transfer and availability counts. |
| `GET /matters/{slug}/intake/{receipt}` | Show 100 selection rows per page with exact source links. |
| `GET /matters/{slug}/intake/{receipt}/export?format=csv` | Download CSV, Markdown or JSON. |
| `GET /matters/{slug}/setup?receipt_page=2` | Discover older selections, ten receipts per page. |

Selections contain at most 10,000 rows. Metadata batches contain at most 2,000
rows and 6 MiB of UTF-8 JSON; the browser splits batches by both count and encoded
size. Invalid types, counts, ordinals or nested descriptors fail before writes.
Paths use the same validated canonical relative path as upload admission; unsafe
names are minimized. Client metadata is not a byte-derived finding.

Mirrored SQLite migration `0025_intake_receipts.sql` adds receipt, item and transfer
tables to the existing control database. It creates no new storage boundary or
worker. Receipt writes count as matter activity. Incomplete metadata alone is not
active processing and cannot strand matter closure. Normal owner closure removes
all receipt rows in the existing deletion transaction; upload and processing work
retain their existing active-work checks.

Receipt page rows/counts and exports use SQLite read snapshots. Complete bundles
materialize at most 1,000 receipts and 100,000 selection rows, with the existing
100 MiB uncompressed export limit also enforced. Oversized bundles fail explicitly
and direct staff to individual receipts; older receipts are never silently omitted.
CSV cells receive the existing formula protection. The final bundle still checks
all other work-product sections and total output size.

## Upgrade, backup and rollback

Back up and verify restoration of the complete application-owned boundary before
an upgrade. The normal backup already includes the SQLite control database and
managed partial uploads. The synthetic normal backup/restore regression verifies
receipt rows, skipped reasons, transfer bindings and seven saved partial bytes.
The test uses real SQLite databases and partial files with a mocked service/restic
runner; it does not claim a new encrypted-repository or PostgreSQL integration
drill. No source originals are added to the backup boundary by this feature.

A stopped synthetic previous-version reader can open the existing Sources page
and saved upload offsets without damaging new receipt tables. Returning to the
current reader resumes the exact bytes with the same receipt/session. This proves
read compatibility, not feature equivalence: an older application has no receipt
UI or receipt exports and must not be used for ordinary receipt-aware review or
closure. After receipts are in use, prefer a forward correction; a rollback needs
the complete verified pre-upgrade backup and an explicit disposition for newer
work. Do not drop the new tables or restore only the control database.

## Synthetic acceptance

The regression suite covers 10,000-item recording, malformed requests, CSRF,
revoked/foreign actors, concurrent retries, exact manifests, canonical paths,
source-version changes, held media, coherent snapshots, CSV protection, pagination,
complete bundles, incomplete selection, activity and deletion. The dedicated
Chrome acceptance exercises actual nested folder input, denied browser storage,
lost successful responses, interrupted/reloaded byte transfer, exact source
viewing, all-skipped selections and normal receipt/final-bundle downloads.

```console
python -m pytest -q tests/test_intake_receipts.py tests/test_intake_receipt_http.py tests/test_backup_consistency.py
python scripts/browser-accept-intake-receipts.py --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver --output /tmp/generated-receipt-acceptance
python scripts/verify-intake-receipt-rollback.py --previous-source /path/to/previous-checkout
```

Browser artifacts contain only generated fixtures. They are additional acceptance
evidence, not required public attachments or proof of confidential-data readiness.

Validation on September 8, 2026: `make check` passed 898 application tests with
nine optional skips, all 194 transcription tests, compilation, Compose and
publication checks. Chrome passed eight dedicated receipt workflows, including
an actual capacity-limited selection whose skipped reason survives reload and
CSV download. All 37 existing loose-file preflight workflows passed before the
receipt-only review correction. The previous-reader check passed unchanged
receipt state and exact seven-byte-offset forward resume. The normal synthetic
backup/restore regression also passed with the separate reviewed selection
state and reason.
