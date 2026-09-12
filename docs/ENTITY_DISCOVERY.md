# Entity discovery and reviewer reconciliation

Slice 17 builds on the manual entity workspace. Open **People, places & things**
and expand a text-review run under **Discover supported mentions**. **Discover
next 10 units** extracts up to ten pending units from that run's sealed slice-12
inventory. Each unit commits separately; stopping between requests preserves
progress. Resume the text review to inventory remaining sources, then continue
entity discovery. No model or background entity worker is required.

The coverage panel distinguishes processed, pending, failed and changed units.
Sources without a sealed inventory remain visibly unprocessed; unavailable
sources are shown separately. Retrying failed discovery selects only failed
units; pending units require the normal discovery action. Processed units are
never overwritten. Later source-version or content-basis changes label frozen
coverage historical. A processed unit means the extractor visited it, not that
it recognized every name or that OCR/transcription was complete.

Coverage uses aggregate counts on the entity index, with up to 20 review runs
per page. A separate coverage view shows up to 50 sources and 50 unit outcomes
per page. Counts describe the whole run, independently of the displayed page.

## What the initial extractor recognizes

`deterministic-entities-v1` is a replaceable local rule implementation. It finds
bounded capitalized name runs without requiring titles, organizations with a
listed suffix, explicit `ID:`, `VIN:`, `serial:`, `badge:`, `plate:`, `account:`,
`identifier:` values and labeled `object:` descriptions, and numeric dates. Explicit `person:`, `name:`,
`witness:`, `alias:`, `organization:` and `company:` lines preserve Unicode names
including scripts without capitalization. No learned model, weights or remote
service are introduced.

This is a bounded recognizer, not general multilingual named-entity recognition.
Unlabeled single-token names, scripts without capitalization, contextual aliases,
unusual organization forms, OCR corruption and ordinary capitalized prose can
be missed or misclassified. Reviewers can correct types and labels, attach
manual support, and create identities without extraction. The synthetic results
in the [dated validation receipt](ENTITY_DISCOVERY_VALIDATION_2026-09-12.json) do not establish real-case recall.

Every detected occurrence initially gets a **separate suggested identity** and
supported mention. The same name twice in a unit produces two distinct mention
IDs and offsets. There is no 75-entity cutoff. A unit with more than 1,000
proposals fails explicitly without saving a partial set. The built-in extractor
stops before constructing proposal 1,001; replacement iterators are consumed
only through that first over-limit item. An aggregate 16 MiB
logical entity payload budget (including retained history and per-row allowance)
admits machine writes conservatively before a unit is saved. Existing manual
work counts toward that budget but is never removed to make room. Budget
exhaustion keeps the unit unprocessed, preserves earlier committed units and
shows an explicit error. Retrying, restoring or changing extractor versions
does not reset this matter budget. It is not a claim about exact physical SQLite
file size. Only the selected units are checkpointed; merely opening or starting
discovery does not copy the entire inventory. Existing text-review population
limits remain unchanged. Each committed unit emits a content-free audit event
before the next unit starts, so a later budget error retains the audit of earlier
saved work.

Streamed unit files use a transient offset index: at most 20,000 offsets across
eight file identities, with no cached source text or persistent index. A first
read validates the existing unit container; subsequent batches seek selected
records directly. Source guards and before/after file-identity checks protect
the read. Changed files rebuild the index; restart and restore need no index
backup. Inline units retain direct ordinal access.

Mentions retain original source/version/unit support, the exact detected text,
character offsets in that original extracted unit, extractor version and their
own review status. Offsets are not byte positions or page coordinates. The
original-source link opens the full unit; the displayed supporting excerpt
retains the existing 6,000-character limit, so an occurrence later in a long
unit can be outside that excerpt. Historical source support remains available
as saved text when its current-source link is disabled.

Dates retain their raw spelling, ambiguity and explicitly supplied timezone.
Slash dates leave day/month order unresolved; missing zones remain unspecified.
No normalized timestamp is guessed, and calendar validity is not asserted.
When the exact same span matches several rules, explicit identifiers take
precedence over objects, organizations, people and dates, in that order.
For example, `ID: 2026-09-12` remains an identifier. Replaceable extractors must
resolve conflicting classifications for one span; otherwise the unit fails
without partial mentions. Cross-version occurrence suppression remains based
on source/version/unit/offset, preserving reviewer corrections.

## Reviewer decisions

Candidate pages inspect 50 identities at a time in name order, with next/previous
controls. Each page proposes similar display names or exact alias overlap; fuzzy
alias variants may be missed. Scoring runs after releasing the workspace writer
transaction, with at most one display-name comparison per identity. A proposal
does not establish identity; transcript speaker clusters are not used as identities.
Open both candidates and their original passages before making a decision.

- **Confirm alias link** records the two identities and adds the source label to
  the destination's aliases without moving mentions.
- **Confirm merge** transfers all mentions to the selected destination, retaining
  both identity records and their correction history. Same-unit mentions remain
  distinct; the emptied source identity stays available for inspection and undo.
- **Keep distinct** rejects the pair in both directions without removing support.
- **Split** transfers a selected mention into a separate identity. Create that
  identity first, then enter its ID and current revision in the reconciliation
  form. The same form allows deliberate reconciliation of dissimilar labels.
- **Undo** reverses a decision only while both entities still have the revisions
  saved by that decision. It preserves mention IDs and review corrections. Later
  shared edits cause a conflict instead of being overwritten; compare the records
  and make an explicit new correction. This is guarded single-operation undo,
  not unrestricted rollback through subsequent edits.

A reconciliation conflict retains the decision, source and destination revisions,
destination ID and selected mention. Compare the current identities, then update
the revision inputs explicitly before retrying. A removed mention remains
visible as the previously selected input, without being silently reassigned.

Entity and mention review statuses are separate. Dismissing a mention retains
it and its support; removing it retains the removal in history. Extraction uses
source-version/unit/offset occurrence receipts independently of extractor
version, so rerunning the same occurrences cannot recreate removed mentions or
overwrite reviewer labels, review statuses, splits or merges. Changed offsets or
source versions can propose new occurrences, always separate from existing
human work. Deleting an identity removes its reconciliation operations while
retaining opaque occurrence suppression receipts until matter purge.

All changes use the existing workspace lock, transaction authorization and
revision checks. Source-backed extraction holds the source guard through commit.
Routes delegate to narrow services and repositories. Existing notebook import,
source-review return paths, manual workflows and older history snapshots remain
supported.

## Storage and recovery

Mirrored migration `0033_entity_discovery.sql` atomically preserves and rebuilds
the constrained entity/mention/history tables, extends supported types and
machine provenance, removes the same-unit uniqueness constraint, and adds
occurrence receipts, extraction coverage and reconciliation history. Deleting a
text-review run cascades its discovery coverage; saved entity mentions, reviewer
decisions and occurrence suppression receipts remain until their own lifecycle
removes them. Manual
attachment remains idempotent. New history remains linear mention deltas;
reconciliation records identify the moved mentions and checked entity revisions.

The control SQLite store remains authoritative on both retrieval profiles.
Individual entity JSON reads identity, mentions, correction history and
reconciliation decisions in one authorized transaction, preserving a consistent
export snapshot even when another reviewer saves a decision immediately afterward. Final
matter bundles additionally include `entities/discovery.json` with frozen source
coverage, unit outcomes, occurrence suppression receipts and reconciliation
records. Bundle source availability is explicitly not revalidated. Matter purge
and retention expiry remove all these records. Source bytes remain governed by
the existing storage/backup contract, not embedded in final work-product bundles.

Stop writers and back up the complete boundary described in
[storage and backup](STORAGE_AND_BACKUP.md) before upgrading. Keep matching code,
control database, session state and managed originals. Restore into a clean
target and verify original bytes, support resolution, coverage and reviewer
history. Rollback uses the verified pre-upgrade backup and matching pre-upgrade
code; never point slice-16 code at slice-17 state. Export later work first because
the old backup cannot contain it. Release tags remain immutable.

Validation commands:

```console
python -m pytest -q tests/test_entity_discovery.py tests/test_entity_workspace.py tests/test_matter_notebook.py tests/test_notebook_conflicts.py
python scripts/entity-discovery-restore-drill.py
python scripts/entity-storage-restore-drill.py
python scripts/browser-accept-entity-discovery.py --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver --output /tmp/generated-discovery-acceptance
```

The HTTP restore regression moves the original runtime and backup offline,
serves the exact synthetic original bytes from the restored target, checks
coverage and reconciliation, performs undo, exports and purges. The migration
drill checks the original slice-16 reader against a clean pre-upgrade rollback.
These are synthetic contributor checks, not installed-node acceptance.

Slice 18 relationships/events, background material, matter memory, proposed
slice 19, capacity expansion, held Mac work and deployment remain out of scope.
