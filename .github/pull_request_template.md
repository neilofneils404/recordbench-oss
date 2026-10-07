## User problem

Reviewers should be able to type an intent without choosing a search engine.
The foundation needs to distinguish exact syntax, requests for every matching
record, and ordinary questions without executing retrieval or sending text away.

## Result

Adds pure `classify(text) -> RouteDecision` in `ask_router.py`, with a frozen
decision and one short explanation. Valid exact syntax takes precedence over
requests for every source; plain words, casual uses of "all", and empty input
remain questions. Invalid syntax falls through to the natural-language rules.

Exact intent comes only from `parse_query` and its structure. The parser now
retains explicit `AND` provenance so ordinary adjacent words do not become
exact searches. Matching, normalization, expression equality/hash and serialized
plans retain their existing semantics. The routing contract and punctuation
limitations are documented in `docs/EXACT_SEARCH.md`.

## Synthetic evidence

- `tests/test_ask_router.py`: 102 synthetic input/expected-kind examples,
  including quoted questions, malformed quotes, precedence, casual "all", and
  record-enumeration variants; also immutable decisions, content-free reasons,
  deterministic results and parser-authority regressions.
- `tests/test_exact_search.py`: explicit/implicit `AND` provenance, nesting and
  unchanged matching, normalized, serialized, equality and hash semantics.
- Router, parser and proximity targeted suite: 247 passed.
- Full `CASE_INTELLIGENCE_STORAGE_RESERVE_GIB=0 make check`: passed (exit 0);
  application: 4,967 passed, 14 skipped; transcription: 330 passed.
  Compilation, all Compose graphs and the tree/history publication sanitizer
  also passed. `ask_router.py` is 77 lines; `git diff --check` is clean.
  This is the existing CI/synthetic-test setting documented in
  `docs/WORKFLOW_LINUX_VALIDATION.md`. The initial default-reserve run was stopped
  after four upload-dependent failures: the test environment cannot meet the
  production 100 GiB free-space reserve. All four pass with the synthetic setting.
- No browser or clean-host acceptance applies to this pure helper.

## Impact

- Security, authorization, or matter isolation (for sensitive changes, include
  the focused assessment, abuse cases, regression evidence and findings disposition):
  Classification consumes untrusted text but does not access sources or execute
  a query. Internal security assessment covered parser rejection and bounds,
  malformed quotes/operators, Unicode/control characters, regex resource use,
  fixed explanations, and source/execution boundaries. The 247 targeted tests
  passed; 20,007 synthetic adversarial/boundary probes produced no crashes;
  1,000 audited calls emitted no file, process or socket events. Nine regex
  stress families through approximately one million characters showed linear
  scaling. Explanations do not echo input. No actionable findings.
  Exact parsing retains its 512-character, 128-token and depth-16 bounds; the
  natural-language fallback has no global input cap. Future integration must
  apply request budgets and existing authorization/source scoping. This
  assessment covers the pure helper, not later retrieval/model integration.
- Storage, deletion, backup, or migration: none.
- Models, licensing, or offline operation: no model or dependency changes;
  classification is local, deterministic and requires no configuration or I/O.
- Operator documentation or recovery: routing precedence and parser limitations
  added to the existing exact-search contract; no deployment changes.

## Checklist

- [x] All examples, fixtures, screenshots, and logs are synthetic and
      environment-neutral.
- [x] No private identity, hostname, address, path, credential, certificate,
      data, transcript, runtime state, or deployment overlay is included.
- [x] Behavioral changes include a regression test and applicable
      documentation.
- [x] `make check` passes, or the exact bounded exception is explained.
- [x] The publication sanitizer passes.
- [ ] The complete outgoing history passed the local pre-push check; PR text
      and attachments were separately inspected before upload.
- [ ] Before merge: actual hosted Codex code review completed on the final
      implemented head, findings were reconciled and a maintainer accepted the
      full head under `docs/PUBLIC_ALPHA.md`, including native commit binding or explicit verified clean-review attestation and
      explicit trusted revalidation immediately before manual merge. Hosted security review is optional;
      labels and quotas cannot waive code review. All Quality, publication,
      Gitleaks and native branch protections remain required.
- [x] No existing release tag was moved or rewritten.

Draft publication and hosted code review are requested. The pre-push check must
pass before upload; final-head hosted review, reconciliation and maintainer
acceptance remain required before merge under `docs/PUBLIC_ALPHA.md`. Security
review was performed internally; no hosted security review was requested.
