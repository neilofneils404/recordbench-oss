# Exit-alpha cruise

Binding execution order for leaving public contributor alpha.
Product slice briefs under `docs/product-slices/` remain the implementation
specs. When numeric slice order conflicts with this file, **this file wins**.

**Last updated:** 2026-09-11

Verified tip of `main`: `c5b507c2a3ffd8ac97734dec01ce6064d345a78e`
(slice **11** merged as [#66](https://github.com/neilofneils404/recordbench-oss/pull/66);
slice **12** already on `main`).

## Cruise order

| Step | Work | State |
| ---- | ---- | ----- |
| 0 | Portable baseline on `main`; alpha blockers #30 / #31 closed | Done |
| 1 | Prove `main`: green Quality gates (including synthetic-browser); clean-host CPU install acceptance; install friction documented | Done |
| 2 | Slice **06** — reusable team groups with explicit matter access | Done |
| 3 | Slice **11** — evidence-driven investigation (durable plan, reasons, checkpoints, zero-hit ledger rows) | Done |
| 4 | Slice **12** — deepen full-text coverage as required to feed durable findings | Done |
| 5 | Slice **13** — hierarchical synthesis (issue- then matter-level) with citations through intermediates | **Next** |
| 6 | Slices **16 → 18** — People / Places / Things workspace, extraction, evidence-backed relationships | After 13 |
| ∥ | Parallel release-readiness evidence (`docs/RELEASE_READINESS.md`) | Ongoing; does not block 13 |

Slice **12** needed no further product PR. **Review all extracted text** is
already on `main` from [#59](https://github.com/neilofneils404/recordbench-oss/pull/59)
(the #47 / #58 family). That work matches
[12-full-text-review-coverage.md](product-slices/12-full-text-review-coverage.md)
and is specified in [FULL_TEXT_REVIEW.md](FULL_TEXT_REVIEW.md): every eligible
extracted unit in a frozen population, durable unit/range outcomes, late-unit
and failed-unit coverage, source-change invalidation, cancellation/resume, and
backup/clean-restore. Selected-passage screening remains a separate mode by
design. Cross-source hierarchical synthesis is **13**, not a 12 gap.

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
