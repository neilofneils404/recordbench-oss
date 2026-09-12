# 19: Synthesize one full-text review with original support

Status: proposed, not scheduled. Depends on 12 and 13. Activate a named sub-step
in the [exit-alpha cruise](../EXIT_ALPHA_CRUISE.md) before implementation.
This brief does not displace the entity sequence or change capacity defaults.

## User outcome

After reviewing all extracted text for a criterion, a reviewer can use the saved
findings to produce a cited synthesis for that same criterion. They can inspect
support, competing evidence, unprocessed ranges, and omitted findings. They do
not have to ask a fresh ranked search to rediscover what the review already found.

## First implementation boundary

Accept exactly one terminal full-text run, its frozen population, criterion,
revision, and authorized matter. Define a versioned input receipt binding source
and extraction identities, coverage, findings, and original locators. Resolve
original text through the existing source verifier; a range decision or earlier
summary is not itself evidence. Refuse incompatible, active, or stale input.

Stream and admit inputs within explicit existing resource limits; account for
all candidate findings and omissions before any completion claim. Do not load an
unbounded ledger into memory or hide truncation behind the existing hierarchy's
small policy. If the selected run exceeds what this first adapter can admit,
show the exact limit and unresolved work without claiming whole-run synthesis.

Pass validated supported findings through the shared hierarchy. Preserve
negative/no-finding outcomes and analysis/extraction failures in coverage even
when they contribute no generated claim. Keep machine findings and human source
decisions separate. Persist enough input identity to invalidate reuse after a
source or relevant run revision changes, with charged calls surviving restart.

Expose one action from the terminal review and reuse the synthesis inspector and
exports. Cancellation, source deletion, membership revocation, and source-set
changes must retain the existing save-time and response authorization boundaries.
Document whether human decisions are frozen context or a later view; do not let
a mid-run edit silently change the synthesis basis.

## Synthetic acceptance

- Distribute supported findings and a late contradiction across more than 12
  extracted units. Require original support for both accounts in final output.
- Include an excluded/no-finding range, failed extraction, failed classification,
  empty source, and unsupported saved text. All remain correctly accounted for.
- Reject an active run, mismatched matter, changed revision, missing original,
  and stale source version; preserve authorized historical output appropriately.
- Interrupt after one completed intermediate; resume without duplicating saved
  nodes or refunding spend. Exhaust a limit and verify honest partial output.
- Verify the browser path from terminal run to synthesis, original passage, and
  export, including keyboard access and understandable recovery.
- Version persisted records; restore a consistent backup into a clean database
  and resume/export. Document rollback compatibility even without a SQL migration.
- Run a representative pinned local-model evaluation separately from deterministic
  plumbing tests. Measure recall and false claims, including competing accounts.

Future work: multiple-run aggregation, partitioned review, adjustable capacity,
and new questions over a completed collection. Each requires its own scope and
acceptance; none follows automatically from this adapter.
