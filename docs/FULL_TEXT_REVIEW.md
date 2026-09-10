# Review all extracted text

The saved-criterion screen offers **Check selected passages**, the existing
search-based screening, and **Review all extracted text**, which visits each
extracted unit in the frozen eligible population. Long units become overlapping
model-sized packets, with a saved outcome for each canonical text range. Human
source decisions remain separate from machine findings. This feature supplies
unit findings and coverage for later Report synthesis; it does not itself make
cross-source claims or establish that every relevant fact was recognized.

## Frozen scope and resource admission

Source IDs, versions, content-basis digests and extraction states are frozen in
the same immediate SQLite transaction as the criterion/run and resource receipt.
Unavailable sources remain in the extraction ledger. Later uploads, changed
source sets and newly available extraction do not expand that population. A
source inventory is staged in bounded transactions and sealed only after the
exact frozen source is revalidated. Until then its full denominator is unresolved.
Replacement text is never mixed into the original review.

The default policy admits at most 1,000 sources, 20,000 extracted units,
10,000,000 canonical characters, 5,000 classifier calls and 64 MiB of charged
ledger storage per run. Each packet contains at most 6,000 characters, including
up to 256 characters of context on each side. Canonical ranges count a character
once. The frozen output limit is 1,200 tokens and is passed through the production
classification service to both OpenAI-compatible `max_tokens` and Ollama
`num_predict`. Lower internal policies are supported; changing defaults does not
rewrite a saved run's policy. Limits are independent, so admitting a source count
does not guarantee its complete text will fit the character or storage budget.

Admission uses shared database authority across processes, before creating queued
work. Actor, matter and instance limits apply cumulatively:

| Resource | Actor | Matter | Instance |
| --- | ---: | ---: | ---: |
| Active runs | 1 | 1 | 4 |
| Reserved characters | 10 million | 10 million | 40 million |
| Reserved classifier calls | 5,000 | 5,000 | 20,000 |
| Active reservations plus retained charged storage | 128 MiB | 256 MiB | 512 MiB |
| Retained runs | 20 | 40 | 200 |

Queued/running work reserves its entire frozen character, call and storage
budget. Terminal runs release active reservations but continue to count their
saved storage and retained-run slot. Inventory checks character, unit and range
limits before inserting each unit. Classifier calls are charged durably before
dispatch; failed or interrupted calls are never refunded. A cancelled response
that has not been checkpointed may need another charged call on resume. Exhaustion
stops the run with a saved reason and leaves unresolved or pending coverage visible.
A new, smaller run is required after an exhausted budget.

Charged storage includes UTF-8 field lengths, row/index allowances, 4 KiB of run
control, and 64 KiB per source reserved for bounded source decisions and human
notes. Each retry/recovery reserves a further 2 KiB for its control events. These
are conservative logical capacity charges, not a measurement of the SQLite file,
WAL, free disk space or backup size. Operator filesystem reserves and backup
retention remain separate. Compact unit locators are limited to 2 KiB and contain
unit ordinal, digest and source support identity without a duplicated full-text
excerpt. Oversized identities fail explicitly rather than being truncated.

## Outcomes, recovery and coverage

The production classifier's `not_identified` outcome is stored as an `exclude`
range. A failed classification remains a failed range while other ranges can
continue. Empty units, ready sources with no units, unavailable extraction,
unsealed inventory and invalidation are coverage gaps. Units and canonical
characters are distinct from original page counts. Unavailable OCR, untranslated
material, email attachment contents and untranscribed recordings do not become
analyzed merely because another part of their source has extracted text.

Every worker write rechecks active membership, current attempt, cancellation and
source identity. Source decisions and terminal saves are also fenced by attempt.
Current citation verification streams each cited source once at recording and
completion, without loading every unit or repeatedly scanning for each citation.
The existing derived-unit format is read incrementally; one existing extraction
unit remains the atomic decode object. A 120,065,536-character JSON-record
buffer ceiling supports a 10-million-character unit even under worst-case
Unicode escaping; oversized or malformed records fail explicitly with unresolved
inventory. Content-basis digests remain compatible. Actual text digests are
checked for every unit, including uncited text, before saving source decisions
and completing the run.

Restart recovery keeps spent calls, storage reservations and the existing fair
actor/matter scheduling history. Saved ranges are skipped; pending ranges can
resume. Repeated recovery/retry cannot grow uncharged event history. Repeated
running cancellation is idempotent: it preserves the first cancellation event
and resource charge, including concurrent requests through separate connections.
Cancellation
keeps a running worker's reservation until it stops; queued cancellation releases
active capacity. Only the run creator may delete a terminal saved text review,
which removes findings and human decisions and releases its retained capacity.
The UI advises downloading first; source files are preserved.

Coverage polling reads only a small counter table and one resource receipt.
Insert/update/delete triggers maintain source, unit, range and character counts,
including unresolved and zero-unit inventories. The UI paginates 100 ranges at
a time. JSON/CSV downloads stream a consistent SQLite snapshot containing all
source, unit and range records, including partial and failed work. The complete
matter bundle includes the JSON ledger and retains its existing bundle byte
limits. Final synthesis consumers should bind a terminal run and revision; an
active forward cursor is not a completion watermark.

After a failed matter close, export readiness and the final bundle use the
frozen source catalog without reopening quarantined source storage. Full-text
ledgers and saved decisions remain exportable; adjacent source-check summaries
retain recorded locations but leave supporting excerpts empty with an explicit
quarantine notice. Saved review records are unchanged.

Standalone JSON/CSV downloads acquire the same matter response lease as other
source-bearing exports. Matter closure and purge wait until the admitted stream
finishes. A ledger-specific response cleanup closes its read-only SQLite snapshot
and releases that lease on normal completion, producer errors, send errors and
client disconnects; a failed download does not leave deletion blocked. The reader
permits successive, serialized iterator calls on different ASGI worker threads.
Authorization is still checked between record batches.

Each JSON/CSV iterator also acquires a run-specific in-process lease before it is
returned, including before the first response prefix. Admission and creator
ledger deletion share the workspace lock, so deletion is refused until that
run's readers finish; downloads of other runs do not block deletion. Exhaustion,
explicit close and iterator errors release the lease. Response cleanup also
closes an unstarted reader when sending headers fails. Direct consumers,
including bundle preparation, close the iterator when abandoning an export so a
byte-limit or writer failure cannot leave deletion blocked. No persistent schema
or saved ledger content changes are required.

Non-member administrators read coverage, paginated ranges, extraction rows and
ledger downloads under their authenticated identity with an explicit read
override. Deactivating the owner or revoking the owner's membership does not
turn an authorized administrator read into an owner-impersonation failure.
Administrator reads remain attributed to that administrator, and the read
override does not grant creator-only ledger deletion. The deletion panel is shown
only to the creator while they retain matter membership; other members and
administrators can read and export the ledger without an unusable delete action.

The Reports workflow uses `resolve_text_report_citations()` for full-text saved
work. It streams frozen sources, including sources with no citations and decisions
beyond the displayed summary limit. It validates actual text digests, frozen
content bases, names and versions, and returns at most 100 canonical citations.
A requested full-unit excerpt over 6,000 characters fails without slicing. Both
direct Save to Report and the guided composer validate the frozen work while
holding the source and workspace guards; the composer validates it again at final
save. Word and Markdown exports use exact streaming citation validation. Reports
remain bounded summaries with a link to the complete saved review ledger.

## Migration, validation and rollback

Additive migrations `0028_full_text_review.sql` and
`0030_full_text_review_limits.sql` are mirrored in both migration locations.
The latter adds resource receipts and coverage counters. Existing 0028 ledgers
are backfilled once under an immediate transaction, with concurrent/repeated
workspace opens serialized. Duplicated unit excerpts are removed while stored
locators and findings remain. Malformed locator bytes remain available in exports
and are refused for opening; oversized legacy ledgers remain readable even when
above new limits. Legacy active runs become failed and cannot resume without new
admission. Their retained charges still count against capacity.

Synthetic tests cover production negative classifications, frozen token requests
in both adapters, late-unit findings, source changes, cancellation and retry,
concurrent admission, persisted spend, UTF-8 storage accounting, constant-size
polls, zero-unit gaps, partial exports, deletion, concurrent legacy migration and
online SQLite backup followed by a clean restore with integrity/foreign-key
checks. The existing selected-review acceptance manifest and cases are unchanged.

The browser acceptance script launches the mode through its ordinary form,
checks late findings and failed-unit coverage at desktop/mobile widths and
downloads the full synthetic ledger:

```sh
PYTHONPATH=src python scripts/browser-accept-full-text-review.py \
  --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver \
  --output /path/to/synthetic-output
```

Before upgrading an existing writer, stop workers and take the consistent backup
in [Storage, backup, and recovery](STORAGE_AND_BACKUP.md). Rollback of this combined
Report/full-text schema requires the verified pre-upgrade backup restored into a
clean target with its matching original application revision. First cancel or
finish text reviews and preserve complete post-upgrade ledgers separately: a
pre-upgrade backup does not contain later work. Older writers do not understand
full-text mode or budgets and must never resume those runs. Retain an upgraded
backup for a later compatible reader. No model revision, model download or
deployment configuration changes are included. Local synthetic tests do not establish model
recall, Linux/GPU capacity, PostgreSQL execution or confidential-workload acceptance.

Every extracted unit's actual SHA-256 must match its stored excerpt digest during
inventory and again before classification. A mismatch invalidates the source and
leaves an explicit needs-attention outcome without sending altered text to the
classifier. A digest computed from already-corrupt text is not source validation.

Source-check CSV, JSON, Markdown and Word exports hydrate saved compact locators
against the frozen source version and content basis. Complete bundles use the
same hydration for their source-check exports. Cited excerpts remain complete,
including units longer than the narrower Report citation limit; compact stored
locators are unchanged. The existing portable export byte bound applies to the
hydrated support, and unresolved, changed or oversized support refuses the export
rather than emitting empty or truncated cited passages. Uncited attention and
coverage outcomes remain exportable.

The source-decision inspector and validation-recovery page resolve the selected decision's compact citations against its frozen source before displaying supporting passages. This read does not persist excerpts. If the source support is unavailable or changed, the inspector shows a caution and omits unresolved passage links; reopen the source and rerun the check before relying on that decision.

Complete JSON/CSV ledgers include source-decision records with machine outcomes, human decisions and notes, reviewer identifiers, and review timestamps in the same consistent snapshot as text-range coverage. Download that ledger before deleting a terminal saved review. A resource-exhausted review cannot resume; its UI directs the reviewer to start a new run with fewer sources while keeping the saved ledger accessible.

Migrated legacy text ledgers remain readable but cannot resume; the review page
directs the user to start a new run. Opening an older full-text run by its saved
link retains the full-text label and ledger access even when newer checks fill
the recent-run list.

Each bundled source check and its full-text ledger share one read-only database
snapshot, including the run, rule version, human validations, notes and validation
metrics. A teammate may adjudicate while the bundle is built without mixing the
old ledger with newer adjacent exports. The run's deletion lease lasts through
all of its bundled review artifacts and is released on success or failure.
