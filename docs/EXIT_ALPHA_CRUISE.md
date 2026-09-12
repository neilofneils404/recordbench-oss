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
and subsequent delivery stages. Proposed slice 19, background material, matter
memory, production imports, and larger capacity are future scoped work, not
claims of current capability or permission to bypass this queue.

**Last updated:** 2026-09-12

Verified `main` snapshot before this receipt update:
`c1ada89bf15ea8f61906de3c62202da4d98e279f`
(hierarchical synthesis landed as
[#73](https://github.com/neilofneils404/recordbench-oss/pull/73), after
PostgreSQL/pgvector CI in
[#70](https://github.com/neilofneils404/recordbench-oss/pull/70) and the
maintainer security-quota policy in
[#71](https://github.com/neilofneils404/recordbench-oss/pull/71)). This receipt
records a verified landed commit, not the self-referential SHA of the commit
carrying the receipt. Slices **11**, **12** and **13** are Done;
**16 → 18** are Next. No work on those slices is included in this receipt.
The `postgres-integration` job passed on the landed #70 `main` commit
`4dea52ce42eeb01ac1cab188a99f7fc44b571ab9` with seven
tests passing and zero skipped
([main CI receipt](https://github.com/neilofneils404/recordbench-oss/actions/runs/34695365785/job/103557849336)).

It also passed on the landed slice-13 `main` commit recorded above: seven passed,
zero skipped
([slice-13 main CI receipt](https://github.com/neilofneils404/recordbench-oss/actions/runs/34699188264/job/103567811020)).

## Cruise order

| Step | Work | State |
| ---- | ---- | ----- |
| 0 | Portable baseline on `main`; alpha blockers #30 / #31 closed | Done |
| 1 | Prove `main`: green Quality gates (including synthetic-browser); clean-host CPU install acceptance; install friction documented | Done |
| 2 | Slice **06** — reusable team groups with explicit matter access | Done |
| 3 | Slice **11** — evidence-driven investigation (durable plan, reasons, checkpoints, zero-hit ledger rows) | Done |
| 4 | Slice **12** — deepen full-text coverage as required to feed durable findings | Done |
| 5 | Slice **13** — hierarchical synthesis (issue- then matter-level) with citations through intermediates | Done |
| 6 | Slices **16 → 18** — People / Places / Things workspace, extraction, evidence-backed relationships | **Next** |
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

## Active implementation: slice 16

Begin the 16 → 18 sequence with [16: entity workspace](product-slices/16-entity-workspace.md).
Deliver manual matter-scoped entities and source-supported mentions first, then
17's extraction/reconciliation and 18's events/assertions in separate reviewable
changes. The first acceptance journey creates a person, attaches two original
passages, revisits both mentions, and keeps another same-name person distinct.
Alias labels do not establish identity or authorize automatic merging.

Keep the workspace easy to reach during source review, preserve search context,
and test keyboard navigation, shared-edit recovery, and source changes. Follow
the [core evolution plan](CORE_EVOLUTION.md) for a narrow entity service and
repository, preserving transaction authority instead of expanding route-level
SQL. Schema work still requires migration, backup/clean-restore, and rollback
evidence. The slice brief and existing release/review gates remain mandatory.

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
