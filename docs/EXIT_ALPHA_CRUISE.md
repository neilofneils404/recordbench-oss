# Exit-alpha cruise

Binding execution order for leaving public contributor alpha.
Product slice briefs under `docs/product-slices/` remain the implementation
specs. When numeric slice order conflicts with this file, **this file wins**.

## Governing product direction

The [product north star](PRODUCT_NORTH_STAR.md) governs what RecordBench is
building: a free, local-first review workspace for case teams, with excellent
manual review, complete exact search, accountable collection processing,
source-supported investigation, and inspectable matter knowledge. This cruise
remains the single binding implementation queue. Feature contracts describe
current behavior; the north star describes intent; release readiness defines
what must be proven before a supported release.

The [September 12 assessment](PRODUCT_DIRECTION_2026-09-12.md) identifies gaps
and subsequent delivery stages. Slice 19 is promoted below only for its first
single-run adapter. Background material, matter memory, production imports,
and larger capacity remain future
scoped work, not claims of current capability or permission to bypass this queue.

**Last updated:** 2026-09-12

## Current upstream receipt

Verified `main` snapshot after slice 18:
`19d57fbec29325ae9b5ab296e6a2adcb18a5e0ec`, the exact merged head of
[PR #82](https://github.com/neilofneils404/recordbench-oss/pull/82), merged
2026-09-12 at 20:06:27 UTC. Its docs prerequisite
[#81](https://github.com/neilofneils404/recordbench-oss/pull/81) landed at
`e0301b9839b8c69d07f40c5f5827ab4873f428d6`.

The final [PR Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34715322212)
and [exact-branch run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34715316801)
passed. Final-head hosted code review completed after its actionable findings
were corrected. Security review did **not** run: the authorized
[verified quota exception](https://github.com/neilofneils404/recordbench-oss/pull/82#issuecomment-5648357396)
preceded full-head maintainer acceptance and native approval. Branch protections
remained unchanged.

The independent [post-merge Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34716107938)
passed on that exact landed commit: application 2,819 passed, nine skipped;
PostgreSQL seven passed, zero skipped; all six jobs green. This independent
readback establishes readiness for the narrow slice-19 promotion below. The
[slice-18 feature contract](EVIDENCE_ASSERTIONS.md) retains its synthetic browser,
original-source, authorization and clean-restore evidence. Local native baseline
failures remain diagnostic, separate from hosted acceptance. This receipt does
not establish deployment, an installed-node update or a supported release.

## Historical post-17 receipt (superseded snapshot)

Verified `main` snapshot after slice 17:
`e9ab89c792b562c2abf27715d15b5f70d3216900`, the exact merged head of
[PR #79](https://github.com/neilofneils404/recordbench-oss/pull/79), merged
2026-09-12 at 18:52:19 UTC. Its prerequisites are merged at their reviewed heads:
13 ([#73](https://github.com/neilofneils404/recordbench-oss/pull/73),
`c1ada89bf15ea8f61906de3c62202da4d98e279f`) and 16
([#77](https://github.com/neilofneils404/recordbench-oss/pull/77),
`3f96b290ca71adbaef37b92e2d9f4d01cf7d226f`). PostgreSQL CI
([#70](https://github.com/neilofneils404/recordbench-oss/pull/70),
`4dea52ce42eeb01ac1cab188a99f7fc44b571ab9`) is also merged; it does not
complete slices 00/08 exact-search acceptance.

Slice 17's [final PR Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34711746368)
passed on the exact head: application 2,765 passed, nine skipped; all jobs green.
Final-head hosted code review completed with no major issues after prior findings
were corrected and reconciled. Security review did **not** run: the
[verified quota exception](https://github.com/neilofneils404/recordbench-oss/pull/79#issuecomment-5647929760)
preceded separate full-head maintainer acceptance and native gate approval.
The separate [post-merge Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34712490352)
completed successfully at 19:05:20 UTC on the exact landed commit: application
2,765 passed, nine skipped; PostgreSQL seven passed, zero skipped; all jobs green.
This is independent of the final PR run. This established the prerequisites for
the subsequent slice-18 promotion.

The [dated slice-17 receipt](ENTITY_DISCOVERY_VALIDATION_2026-09-12.json)
retains local synthetic browser, migration/rollback and restored-original-source
evidence, including baseline-equal local failures. Those failures are diagnostic;
the later hosted pass is separate acceptance evidence. The receipt's pending
final-head review wording describes its preparation time and is superseded by
this landing receipt. None of this establishes a supported release, deployment,
learned-model quality or confidential-casework readiness.

## Historical pre-17 receipt (superseded snapshot)

The following receipt remains evidence for slice 16, not the current tip.
Verified `main` snapshot before slice 17:
`3f96b290ca71adbaef37b92e2d9f4d01cf7d226f`, the protected fast-forward of
[slice 16 PR #77](https://github.com/neilofneils404/recordbench-oss/pull/77).
GitHub confirms MERGED at that exact commit; contract issue #76 is closed as
implemented. Final PR CI passed, hosted code findings were reconciled, and a
verified security-quota exception (not a completed security review) preceded
maintainer acceptance and native approval. The separate
[post-merge Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34706467703)
completed successfully on that exact landed commit. This is independent of
the already-passing final PR checks. See the
[dated slice-16 receipt](ENTITY_WORKSPACE_VALIDATION_2026-09-12.json) for tested
scope and local baseline failures; those are diagnostic, not waived gates.

## Cruise order

| Step | Work | State |
| ---- | ---- | ----- |
| 0 | Portable baseline on `main`; alpha blockers #30 / #31 closed | Done |
| 1 | Prove `main`: green Quality gates (including synthetic-browser); clean-host CPU install acceptance; install friction documented | Done |
| 2 | Slice **06** — reusable team groups with explicit matter access | Done |
| 3 | Slice **11** — evidence-driven investigation (durable plan, reasons, checkpoints, zero-hit ledger rows) | Done |
| 4 | Slice **12** — deepen full-text coverage as required to feed durable findings | Done |
| 5 | Slice **13** — hierarchical synthesis (issue- then matter-level) with citations through intermediates | Done |
| 6 | Slice **16** — manual People / Places / Things workspace | Done (#77) |
| 7 | Slice **17** — entity discovery and reviewer reconciliation | Done (#79) |
| 8 | Slice **18** — evidence-backed relationships and events | Done (#82) |
| 9 | Slice **19** — first substep: synthesize one terminal full-text run for its criterion | **Next — narrow implementation** |
| ∥ | Parallel release-readiness evidence (`docs/RELEASE_READINESS.md`) | Ongoing alongside active slices |

Slice **12** needed no further product PR. **Review all extracted text** is
already on `main` from [#59](https://github.com/neilofneils404/recordbench-oss/pull/59)
(the #47 / #58 family). That work matches
[12-full-text-review-coverage.md](product-slices/12-full-text-review-coverage.md)
and is specified in [FULL_TEXT_REVIEW.md](FULL_TEXT_REVIEW.md): every eligible
extracted unit in a frozen population, durable unit/range outcomes, late-unit
and failed-unit coverage, source-change invalidation, cancellation/resume, and
backup/clean-restore. Selected-passage screening remains a separate mode by
design. Cross-source hierarchical synthesis is **13**, not a 12 gap.

Slice **13** consumes persisted investigation findings through issue groups and
cross-group matter sections, retaining original source/version/location support.
Versioned checkpoints preserve budgets across interruption; partial results,
unsupported findings and omitted groups remain explicit in pages and exports.
Synthetic acceptance covers 24 units, support and contradiction, restart and
backup/clean restore. The documented local-model evaluation retained both decisive
accounts and all 24 citations under its stated evaluation settings. See
[HIERARCHICAL_SYNTHESIS.md](HIERARCHICAL_SYNTHESIS.md) for the receipt and limits.
The final PR application suite passed 2,723 tests (nine skipped), with hosted code
review, a verified maintainer security-quota exception, acceptance and protected
fast-forward of the exact no-reply head.

## Landed slice 17 and its limits

[Entity discovery](ENTITY_DISCOVERY.md) consumes sealed slice-12 unit inventories,
retains each recognized occurrence, and offers reviewer-confirmed alias links,
merge/split and guarded undo. Coverage records visited units, not complete name
recall. Its rule-based extractor has limited recall and can misclassify prose;
no learned NER quality or automatic identity resolution is claimed. Entity work
is exported separately and does not yet feed automatic Report compilation.
Full-text findings still do not feed hierarchical synthesis; the first slice-19
adapter is the authorized next implementation below.

## Landed slice 18 and its limits

[Events and assertions](EVIDENCE_ASSERTIONS.md) preserve typed entity roles,
raw/uncertain dates, supporting and competing originals, and explicit reviewer
status and corrections. Entity detail and paginated chronology expose the
records. Shared names, co-mentions and speaker clusters do not establish identity
or relationships. This manual workflow does not add automatic relationship
inference or entity-to-Report compilation.

## Active implementation: slice 19, first single-run adapter

Implement the first substep of [19: full-text synthesis](product-slices/19-full-text-synthesis.md):
one terminal full-text review, its existing criterion and authorized matter,
through the landed shared hierarchy. Bind a versioned immutable input receipt to
the consistent run, relevant decision revisions, frozen population, source and
extraction identities, coverage, finding identities and original locators. Stream
enumeration and bounded admission; preserve inspectable omissions, including
oversized originals, failures and no-finding ranges. Earlier generated summaries
and range decisions never become original evidence.

The content-free provenance/storage contract is
[#83](https://github.com/neilofneils404/recordbench-oss/issues/83).
Require cancellation/recovery and durable charging, active/stale/cross-matter
refusal, save-time and response authorization, browser/source/export acceptance,
versioned backup/clean restore and rollback, and a separate pinned local-model
evaluation. Human decisions remain separate frozen context with revision checks.
The new action requires CSRF protection and a negative request regression.
Bind the input ledger atomically: concurrent creator deletion must either be
blocked by a dependency/lease or invalidate active synthesis without losing
charged work. Include synthesis in active-work matter-close refusal, complete
purge cleanup and late-worker fencing; prove concurrent deletion and clean purge
with synthetic records.

This promotion authorizes implementation, not acceptance. Multiple-run
aggregation, new questions, capacity increases, entity-to-Report integration,
background/memory, production imports, held Mac integration and deployment stay
outside this substep. Do not mark 19 Done before its reviewed implementation
actually merges and its independent post-merge checks pass.

Every subsequent slice must state its reviewer outcome, actual processed scope,
original support, human/machine distinctions, and recovery path. Manual review
and accessibility are part of delivery, including useful behavior without AI.

## Hold

Do not take these as the next ticket:

- Apple Silicon / Mac exit path (#33, #34)
- Reopenable matters and mega-integrations
- Charging-document matter frame (after cast exists)
- Agentic playbook / single-shot “Prompt 1” client-summary architecture
- One-shot “ask the corpus” as the complex-case product story
- Raising one retrieval limit instead of slices 11 / 13

## Complex-case direction (not this sprint)

Client-specific discovery summaries on large matters need multi-step hybrid
exact + semantic search, hit ledgers, and cited-or-gap synthesis—not smarter
one-shot rerank.

Ship that capability as three stages after 06:

1. **11** — multi-hop search ledger honesty (including explicit zero hits)
2. **13** — cited hierarchical summary on modest synthetic corpora
3. **16 → 18** — cast / aliases / relationships

Do not claim million-chunk Prompt-1 scale until capacity policy is a separate
gate (`docs/INVESTIGATION_BUDGETS.md`). The application owns citations, zero-hit
rows, budgets, matter isolation, and human-vs-machine provenance. Models may
propose queries and draft prose only.

## PR rules

1. One cruise step (or named sub-step) per PR stack.
2. Implement only the row marked **Next** unless this file is updated first.
3. Follow the matching brief in `docs/product-slices/`.
4. Synthetic fixtures only; no private deployment material.
5. Preserve authorization, citations, human-vs-machine provenance, offline
   posture, and explicit incomplete states.
6. When a step lands on `main`, update the State column in this file.

## Pointers

- [product-slices/README.md](product-slices/README.md)
- [06-team-groups.md](product-slices/06-team-groups.md)
- [11-evidence-driven-investigation.md](product-slices/11-evidence-driven-investigation.md)
- [FULL_TEXT_REVIEW.md](FULL_TEXT_REVIEW.md)
- [13-hierarchical-synthesis.md](product-slices/13-hierarchical-synthesis.md)
- [RELEASE_READINESS.md](RELEASE_READINESS.md)
- [CONTRIBUTOR_BACKLOG.md](CONTRIBUTOR_BACKLOG.md)
