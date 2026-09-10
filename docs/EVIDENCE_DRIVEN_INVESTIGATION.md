# Evidence-driven investigation

An investigation starts with the reviewer's question. Subsequent searches follow
identifiers, dates, quoted phrases, and multi-word names found in newly selected
passages. The details page shows each search, its reason, the motivating source,
and proposals that have not been searched. An anchor is a lead, not a verified
fact: matching records may corroborate or contradict it.

The planner is deterministic and source-close. It does not ask a model to choose
tools, permissions, source sets, or resource limits. Proposals contain only a
literal anchor, its search text, a fixed reason, and the motivating support token.
Unknown fields, changed search text, missing support, and anchors absent from the
passage are rejected. Uploaded instructions are treated as searchable text.
The application applies the original matter and source-set scope to every search
and rechecks membership and source versions between steps.

## Budgets and stopping

New runs allow at most five searches and 15 minutes of search-step time. The
cooperative time limit is checked between calls; an in-flight retrieval or model
call can finish after it. Final synthesis has its separate existing packet and
output limits. A run also stops when it has 72 unique evidence passages, exhausts
its proposal queue, or completes two searches without selecting new evidence.
Queries are deduplicated without regard to case. Previously selected passages
are excluded before selection and are not regenerated in another search pass.
The final synthesis still uses at most 12 passages: this is not whole-matter
coverage or hierarchical synthesis.

The proposal queue holds at most 40 entries, with at most eight added per pass.
Matching is intentionally conservative: unrecognized names, date formats, or
unresolved questions without an extractable anchor may need a reviewer to start
another question. The planner does not infer relationships from a name alone.

## Checkpoints and additional work

Cancel safely preserves the last committed checkpoint. Resume investigation
reuses its completed searches, evidence, pending queue, and consumed search time.
It does not silently grant more resources. An in-flight call may be discarded
when cancellation is acknowledged, as with existing investigation accounting.
A completed run with remaining proposals offers an explicit additional budget
of one to five passes, adding three search minutes per pass. The lifetime ceiling
is 15 passes and 45 search minutes; the evidence and synthesis limits do not grow.
Only the initiating reviewer can resume or extend the job. Repeated submission
while it is queued or running does not grant another extension. A form from an
older budget is rejected, and each extension is recorded in the saved plan.
Prior completed conversation messages remain; a continued synthesis produces a new message.

Changed source versions or source availability invalidate the checkpoint and its
dependent searches and findings. A resumed worker rebuilds from the original
question within the unspent budget (discarded passes and consumed time are not
refunded); stale findings and pending proposals are hidden on the details page.
Existing export checks also require the saved evidence to resolve exactly.
Legacy fixed-query investigations retain their query order and cannot receive
adaptive budget extensions. Newly processed legacy work also uses the cooperative
search-time ceiling.

## Storage and validation

Planner version, pending searches, consumed search seconds, stopping reason, and
pass provenance are stored in the existing JSON columns. There is no SQL schema
migration. Existing fixed-query checkpoints remain readable. Downgrading the
application while adaptive jobs are active is unsupported; finish or cancel them
before a downgrade and retain an application-compatible backup.

`tests/test_investigation_planner.py` uses synthetic uploaded records with an
identifier chain reaching a competing account. It exercises real saved source
locators with deterministic retrieval routing so planner behavior is measured
separately from ranking and model quality. It covers cancellation/resumption,
explicit continuation, duplicate submission, source invalidation, budget limits,
and SQLite online backup followed by a clean restore and integrity check.
`tests/test_investigation_budget.py` checks accounting against UI and exports.

These tests do not qualify the configured local model. Representative offline
model evaluation remains separate: confirm that source-backed claims survive
verification and that a competing account is retained in synthesis. No model,
revision, license, or deployment configuration is changed by this slice.

### Local acceptance receipt — September 10, 2026

- 249 focused investigation, budget, recovery, email-coverage, report-material,
  report-basis, and compilation tests passed on macOS.
- The full application run recorded 2,465 passed, 9 skipped, and 126 failures.
  An unchanged `e44e485ab3eca94b7e5588765df58f7f4b2b4786` baseline reproduced
  125 failures, including Linux containment fixtures and Linux binary paths.
  The remaining legacy report fixture was updated to include its empty plan;
  it passed in the subsequent 249-test run. This is not a green Linux CI receipt.
- Chromium acceptance at 1440×1000 and 390×844 verified the plan disclosure,
  source-backed pending proposal, and explicit two-pass continuation submission.
- The working-tree publication sanitizer and `git diff --check` passed.
  No model-quality or downstream deployment acceptance is claimed.

### Empty-search ledger

Every completed pass records its query, reason, motivating support token when
applicable, `hit_count`, `selected_passages`, and `retrieval_outcome` in the
checkpoint and final result. The hit count describes returned passages within
the retrieval budget, not the total number of matching chunks in a corpus.
A successful empty search records `hit_count: 0` and `zero_hits`. A search that
returns only already-selected evidence records `no_new_evidence` and zero new
selected passages. Unavailable retrieval records an unknown (`null`) hit count
and `unavailable`, never a claim of zero hits. These outcomes and their empty-pass
explanations appear beside each search in the details plan and in JSON exports.
Synthetic regressions assert checkpoint persistence, final persistence, visible
plan rows, and exports for all three cases. This does not qualify million-chunk
Prompt-1 ledgers or expand synthesis beyond the slice-13 boundary.
