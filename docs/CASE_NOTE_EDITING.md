# Shared case-note edits and recovery

Current contract, September 5, 2026.

Case-team members already share saved case notes, source references and current
editor attribution. A member can open **Case notes → Edit**, change the note,
and save. This change protects that existing workflow from older forms
silently replacing newer teammate work.

When a note changes after the form was opened, **Review changes** shows the
current saved note, its editor and source links alongside every unsaved field:
type, status, title, details, date/time label, and pinned state. The staff member
can compare and adjust those fields before saving again. A further intervening
edit produces another conflict; the proposed text remains available. Ordinary
validation errors also retain the submitted fields for correction.

Confirm, Dismiss and Delete also refuse an old displayed version. Staff return
to Case notes and review the current note before trying the action again. A
status-only action changes status and editor attribution without rewriting the
title, details, date, type, pinned state or source references. If another member
deletes a note while someone is editing, recovery retains that person's text
for copying, with no save action that could recreate the deleted note.

## Storage and HTTP contract

The existing `updated_at` value is the opaque edit token; no schema migration
or additional source/work-product storage is introduced. Every successful edit
or status change advances it beyond the preceding value, even when the clock
repeats or moves backward. An away-and-back edit therefore invalidates an old
form. These tokens are concurrency checks, not authority grants or a historical
revision archive.

Each of these CSRF-protected endpoints requires the displayed
`expected_updated_at`:

- `POST /matters/{slug}/notebook/items/{item_id}` — complete authored-field edit;
- `POST /matters/{slug}/notebook/items/{item_id}/status` — review status only;
- `POST /matters/{slug}/notebook/items/{item_id}/delete` — deliberate deletion.

Store methods require that argument too. Under one SQLite immediate transaction,
they recheck active principal, active membership, active matter and the exact
matter/item identity, compare the displayed token, then mutate. Two connections
editing the same displayed version can admit only one edit. Missing/stale tokens
produce 409; an invalid edit produces 400 with its fields retained. A deleted
note's submitted edit produces recovery at 409 without recreating anything.
Unauthorized users cannot use recovery to inspect a note or another matter.
Administrators without membership retain the existing read-only notebook policy.

The success audit and current-editor attribution retain their existing behavior.
No old/new note bodies are added to audit. Source references remain attached to
the same note/source versions; saved answer context and Report copies retain
their existing snapshot semantics. New exports include the accepted current
note and its ordinary exact source support.

## Validation and operational limits

Synthetic regression covers stale edits/review/delete, simultaneous independent
connections, repeated clocks, changed-text restoration, cross-matter canaries,
revoked/inactive membership, closing matters, all-field recovery, escaped text,
missing tokens, retry and deleted-note recovery. The existing notebook tests
still verify provenance, deletion and frozen answer context, using the new
required edit token.

`scripts/browser-accept-notebook-conflicts.py` starts a temporary loopback
application with two distinct synthetic reviewer sessions. Seven workflows
cover real upload and source-supported notes, shared visibility and attribution,
repeated conflict recovery, stale review/delete, deleted-note draft recovery,
source opening, exported work and deliberate closure. Desktop/mobile screenshots
and a content-free result can be retained with explicit Chrome/driver paths:

```sh
PYTHONPATH=src python scripts/browser-accept-notebook-conflicts.py \
  --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver \
  --output /path/to/synthetic-results
```

The full application suite passed 766 tests with 9 environment-dependent skips;
35 focused notebook/conflict/Rename tests passed. All seven final Chrome
workflow checks passed, including recovered edits submitted in a mobile
viewport. Publication scan, compilation and whitespace checks passed.

This is protection against overwriting current work, not durable draft storage
or a browsable edit-history feature. Unsaved text remains in the recovery page;
leaving that page can lose it. Deleted-note recovery offers copying rather than
restoring another person's deletion. Existing schema remains readable by older
software, but old application writers cannot enforce this contract: do not mix
old and new writers when relying on conflict protection. Rollback retains saved
notes and sources while removing these guards. Refresh forms after a version
change; old forms without tokens receive recovery on the new version.
