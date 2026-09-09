# Review all extracted text

The saved-criterion screen offers two explicit modes. **Check selected passages**
performs the existing faster search-based screening with one source decision.
**Review all extracted text** visits every extracted unit of the frozen eligible
source population, splits long text into model-sized ranges, and retains each
attempt in a separate coverage ledger. Human source adjudications remain separate
from machine findings. This first slice provides unit findings and coverage;
cross-source hierarchical synthesis is a later consumer.

At admission, the source IDs, versions, content-basis digests and extraction states
are frozen in the same transaction as the existing criterion/source run. The
full-text ledger also preserves unavailable sources in the selected population.
Later uploads, source-set changes and newly available extraction do not expand it.
A source's unit inventory is staged incrementally and sealed only after the exact
frozen source is revalidated. Its total denominator remains explicitly unresolved
until that inventory is sealed. Missing or replaced source text is invalidated;
replacement text is never mixed into the original run.

Each call receives at most 6,000 characters and the shared 1,200-output-token
limit. Canonical ranges cover every character exactly once, with 256 characters
of context on each side where available. The overlap helps preserve meaning
around raw character boundaries; it does not establish perfect recognition of
cross-boundary or cross-document facts. Repeated identical findings within a unit
are grouped for the source summary, while every range outcome remains in the
ledger. No source-count or total-character limit is inferred from workstation
memory. Execution concurrency follows the existing review coordinator and model
service settings; server throughput and model recall need independent validation.

A failed classification is retained as a failed range and other ranges continue.
Empty units, unavailable extraction, unfinished inventory and source invalidation
remain distinct from processed text. Counts of units, text ranges and canonical
characters are separate from original page totals. Email attachment contents,
unavailable OCR, and untranscribed media are not analyzed merely because their
parent source has some text. Completion means outcomes were recorded for the
available extracted-text work; it never establishes that every relevant fact was
recognized or that the original collection was fully readable.

## Persistence, cancellation and interfaces

Migration `0028_full_text_review.sql` is mirrored in both migration locations. It
adds a full-text mode marker, frozen source inventory, unit records and range
checkpoints beneath existing review runs. It does not rewrite source extraction,
criteria or human decisions. Unit records retain original exact source citations;
range records retain canonical and context positions, state, verified outcome,
rationale, deduplication key and worker attempt. Every worker save rechecks active
matter membership, the current run attempt, cancellation and source identity.
Source decisions and completion/failure calls are also fenced by attempt, so a
worker returning after restart cannot overwrite a resumed run.

The current review coordinator resumes saved pending source decisions. Within a
full-text source, already recorded ranges are skipped; a call interrupted before
its checkpoint can run again without creating duplicate rows. Cancellation stops
between calls and before checkpointing. Failed ranges remain explicit completed
attempts; a new run can revisit them after resolving the cause. Existing active
review runs block matter closure. Removing a run or matter cascades the new tables.

The derived-unit reader streams the existing JSON container one unit at a time.
It avoids a whole-document materialization for inventory/content fingerprints;
the largest existing extraction unit remains the atomic decode/citation object.
Model packets, database fetches and result pages are bounded independently. The
source-content digest remains byte-for-byte compatible with the prior format.

`FullTextReviewLedger.rows()` exposes keyset pagination without a total population
or Report section cap; source extraction rows and exact unit citations are
separately available. Only sealed inventories appear in the paginated range API.
A downstream final compiler should bind a terminal run and its revision. Active
readers must refresh pending outcomes rather than treat a forward-only cursor as
a completion watermark. The browser shows 100 ranges per page and summarizes
extraction records; complete JSON/CSV downloads stream a dedicated SQLite snapshot
including all sources, units and ranges. The JSON ledger is also included in the
complete matter bundle. Existing bundle byte limits fail explicitly before any
new ledger can be silently omitted; standalone ledger downloads are streaming.

## Validation and rollback

Synthetic regression coverage includes a decisive fifteenth unit, a failed unit,
continuous character coverage and overlap, source replacement during a model
call, resumed work without duplicate findings, stale-attempt rejection,
cancellation, revoked/foreign access, unavailable extraction snapshots, complete
JSON/CSV and bundle preservation, compatible content fingerprints, and deletion
cascades. An online SQLite backup restores into a fresh WorkspaceStore with saved
partial outcomes and clean integrity/foreign-key checks.

The existing optional-overview acceptance scenario now holds the workspace
lock while its synthetic fixture updates the shared SQLite connection. This
prevents a background coordinator commit from racing the fixture transaction;
all original scenario assertions remain unchanged. The frozen pack records the
reviewed test-node and containing-file digest changes and updates its aggregate
fingerprint. Case selection and source-fixture digests remain unchanged.

The browser acceptance script launches this mode through the ordinary form,
checks the late finding and failed-unit denominator, inspects desktop/mobile
rendering, and downloads all 15 synthetic ranges. Run it with the repository's
Selenium test environment:

```sh
PYTHONPATH=src python scripts/browser-accept-full-text-review.py \
  --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver \
  --output /path/to/synthetic-output
```

No model revision or deployment configuration changes. Before rolling back to
an older writer, cancel/finish full-text runs and preserve their complete ledgers:
older code ignores the mode marker and cannot safely resume full-text work.
The additive tables remain readable by the new version after rollback; do not
drop them to roll back application code. This is local synthetic/browser evidence,
not Linux/GPU capacity, PostgreSQL execution, clean-install or real-model recall
qualification. The target work-machine checks remain separate.
