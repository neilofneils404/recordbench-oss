# Continuity B — explicit durable context selection

Status: **Implementing; acceptance and landing pending.** The existing
[cruise](../EXIT_ALPHA_CRUISE.md) is the binding queue. C is not selected.

Reviewed baseline: `0d59d5fe4f7be575a66039274415de945a6d5db5`.
Implementation base: `91a97d2ef2b7d4733551a9189bd9c2c7c50c692c`.
The newer commit corrects test lease timing and documents that correction; it is
preserved. The original checkout predates A and has unrelated onboarding edits;
those remain untouched in that checkout. This increment uses an isolated branch.
The companion B/C proposal informs this contract; only the user's B scope is
selected, not its C instructions or model evaluation.

## Selected contract

One empty-by-default selection per matter and reviewer. Knowledge stays shared;
selection ownership is neither private notes nor a team default. Typed stable
references identify notes, entities and assertions (including events), including
all existing review statuses and origins. Selection never confirms truth.
Persist ordered references, approval stamps, selection revisions and attribution,
not copies of current facts. Note versions are opaque updated_at tokens; entity
and assertion versions are actual revisions. Support and role dependencies are
tracked separately. No truncated A projection is used as authoritative context.

GET and preview do not write selections or knowledge. Mutations use the existing
source guard, authorized connection and transaction, CSRF and current authority.
Concurrent changes require explicit recovery. Missing records stay missing;
changed records require explicit reapproval. Remove/reorder never refresh other
approvals. No same-name merge, record recreation or automatic re-add.

Fifty references is a storage/UI limit, not a model-fit promise. Bound reference
scans and serialized bytes before loading full records. Complete exports include
attributed selection manifests; note-only exports and historical answer scopes
are unchanged. Add a paired migration, stopped-backup/clean-restore and purge
coverage. Mixed-version writers are unsupported; stop writers before upgrade,
retain a complete pre-upgrade backup and use its matching release for rollback.
Ordinary exports are not restore archives.

No model calls, prompt/retrieval changes, jobs, Report-memory compilation,
infrastructure changes or lifecycle reopening. Saved selections are **not yet
consumed by answers**. B acceptance requires synthetic service, HTTP and existing
browser-runner evidence, restart, migration/restore/export/purge, current Quality
and publication checks. Required landing remains pending until separately
authorized. Exact executed evidence and handoff will be appended here.

## Executed evidence — first persistence increment

Python 3.12, synthetic fixtures, `PYTHONPATH=src` with the existing contributor
environment. `python -m pytest -q tests/test_matter_context.py
tests/test_matter_knowledge_workflow.py`: **45 passed**. Covers all review states,
two owners, same-name identities, away-and-back note edits, role/source changes,
concurrent revisions, bounded materialization, missing/removal behavior,
SQLite backup/clean restore/restart/export/purge, and unchanged A workflows.
`python scripts/publication-check.py --skip-history`: generic working tree
**CLEAN**; history was not scanned. Initial development tests exposed a missing
migration registration and fixture argument errors; these were corrected before
the passing run. HTTP/export/browser and full gates are still in progress.

## Implementation decisions

The UI opens complete bounded inspection from A's typed record links and adds a
Selected context section to Case notes. Deterministic Move up/down, Remove and
Clear actions use selection revisions. Add and Accept current basis additionally
require the exact server-resolved approval stamp displayed during inspection.
Conflicts retain the attempted action, ID, revision and stamp alongside current
state; no automatic retry or merge occurs. Unrelated entries retain their old
approval stamps even when another entry is reconciled. Missing and oversized
entries remain removable. Existing entity merge/split operations retain their
stable records; B detects their revision changes and never substitutes a target
identity. The existing editor remains responsible for repairing assertion roles.

Approval fields are the real record version plus separate deterministic hashes
of record fields, exact support metadata/availability and typed role dependencies.
Notes use opaque `updated_at`, including away-and-back invalidation. Fingerprints
are change detectors, not a historical archive: previous fact bodies are not
copied. Inspection labels current fields and the approved version separately.
All attached support within the bound is inspected, including late competing
accounts; no A first-two-reference projection is admitted as complete context.
Unavailable support may be deliberately retained as labeled orientation; it never
gains a live-original link or truth status from selection.

Bounds: 50 selected references; 200 source references and 100 roles per inspected
record; 1,000 dependency rows and 512 KiB before full materialization per selection
inspection, plus an independent 512 KiB serialized bound. Candidate inspection
has its own bounded allowance. No correction history is loaded. Complete export
has a separate 1,000-owner / 8 MiB manifest ceiling and existing bundle bounds.
This does not promise that any selection will fit a future model request.

## Executed evidence — workflow and recovery

All material was synthetic; no live generator was enabled. Commands used the
existing Python 3.12 contributor environment, with `PYTHONPATH=src` for this
worktree and `umask 022` for account-directory tests.

- `python -m pytest -q tests/test_matter_context_workflow.py`: **6 passed** for
  initial HTTP flows, conflict recovery, exact original returns, two reviewers,
  CSRF/admin/revocation, note-only exports, full runtime restart/clean restore and
  complete export/purge. The first attempt found an omitted bundle allowlist
  entry and an incorrect test expectation for existing admin POST denial; both
  were corrected before the pass.
- Expanded B service and HTTP suites: **19 passed**, including transaction
  ownership/rollback, read-only identity validation, dependency count/byte limits,
  separate SQLite connections, escaped instruction-like text and machine origin.
- `python scripts/context-storage-restore-drill.py`: **passed**, upgrading the
  reviewed baseline, preserving frozen legacy answer scopes, restoring B state
  and rolling back the pre-upgrade backup with its matching baseline reader.
- `python -m pytest -q tests/test_review_bench_v2_postgres.py --deselect
  tests/test_review_bench_v2_postgres.py::test_live_learned_dense_only_paraphrase_and_unsupported_abstention
  --junitxml=/tmp/recordbench-context-postgres-results.xml`, with the existing
  pinned pgvector image in a disposable test container: **7 passed, one explicitly
  deselected**. `check-postgres-test-report.py` confirmed zero skipped. The test
  container was removed. No model evaluation was requested or run.
- Bundled transcription `PYTHONPATH=src python -m pytest -q` from
  `services/transcription`: **194 passed** (all collected cases, exit 0).
- `python -m compileall -q src scripts tests` and `./scripts/compose-check.sh`:
  **passed**, including standard, Kerberos and local-account graphs.
- The existing Quality read-only installer diagnostic snippet: **passed**;
  no application node was installed or changed.
- `python scripts/run-browser-acceptance.py --archives /path/to/verified-archives
  --output /tmp/recordbench-context-pinned-suite`: **all nine journeys passed**,
  Chrome **153.0.8010.36**, including B's seven checks. Native keyboard save,
  source-return navigation, concurrent tabs, restart/reload, same-name IDs,
  explicit reconciliation/removal, Light/Dusk and 390-pixel reflow passed.
  The initial standalone B run hit a browser navigation timing issue; the
  corrected runner waits for the old element to detach, and the rerun passed.

An expanded focused run had **251 passed, one failed** because a new bound test
intercepted allowed reads of other selected identities as well as its oversized
fixture. The test was narrowed to the oversized identity; the 19-test B rerun
passed. A broader authority run also included an initially invalid machine-note
fixture without required original support; support was added, preserving the
existing source guard. These were test-fixture errors, not waived requirements.
The first full application attempt was deliberately interrupted at **636 passed,
one skipped** to incorporate the transaction-ownership correction; it is not a
full-suite pass. Final full-suite and final browser evidence follow below.
