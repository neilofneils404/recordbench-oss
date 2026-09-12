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
and subsequent delivery stages. Slice 19's first single-run adapter is landed
as recorded below. Multiple-run aggregation, new questions, background material,
matter memory, production imports and larger capacity remain separately scoped
work. This receipt selects no further product step.

**Last updated:** 2026-09-12

## Current upstream receipt

Verified `main` implementation snapshot after slice 19's first adapter:
`95f290bf350742bc77c915eb0269c774069f3633`, merged in
[PR #85](https://github.com/neilofneils404/recordbench-oss/pull/85) at
2026-09-12 at 21:59:37 UTC. Its scope prerequisite
[#84](https://github.com/neilofneils404/recordbench-oss/pull/84) landed at
`126a468a707a6f9b66d3a4f2565585b54ff98244`; its separate
[post-merge Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34719400464)
passed all six jobs: application 2,819 passed, nine skipped; PostgreSQL seven
passed, zero skipped.

The [final PR Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34720656875) passed on
`95f290bf350742bc77c915eb0269c774069f3633`: application 2,945 passed, nine skipped; PostgreSQL seven passed, zero skipped; all six jobs green.
[Hosted code review](https://github.com/neilofneils404/recordbench-oss/pull/85#issuecomment-5648909015) covered that head after findings
were resolved or reconciled. Security review did **not** run: the authorized [verified quota exception](https://github.com/neilofneils404/recordbench-oss/pull/85#issuecomment-5648923555) was recorded for this exact head before maintainer acceptance.
[Full-head maintainer acceptance](https://github.com/neilofneils404/recordbench-oss/pull/85#issuecomment-5648957842) preceded merge.
Native gate approval and strict protection were verified before the normal protected fast-forward; independent readback confirmed that protections remained unchanged.

The independent [post-merge Quality run](https://github.com/neilofneils404/recordbench-oss/actions/runs/34721488683) passed
on `95f290bf350742bc77c915eb0269c774069f3633` at 2026-09-12 at 22:11:43 UTC:
application 2,945 passed, nine skipped; PostgreSQL seven passed, zero skipped; all six jobs green. This is separate from the final PR run.
The [feature contract](FULL_TEXT_SYNTHESIS.md) and
[dated acceptance](FULL_TEXT_SYNTHESIS_ACCEPTANCE_2026-09-12.md#landing-addendum)
retain synthetic source, browser, recovery and qualified model evidence. The
default model wire probe failed; the passing fixed-corpus evaluation explicitly
used `think=false`. Native baseline-equal failures remain diagnostic. This
accepts the first upstream adapter only, not an installed-node update,
deployment, greater capacity or a supported release.

## Historical post-18 receipt (superseded snapshot)

This receipt records readiness at the time of the first slice-19 promotion.

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
| 9 | Slice **19** — first substep: synthesize one terminal full-text run for its criterion | Done — first adapter only (#85) |
| ∥ | Parallel release-readiness evidence (`docs/RELEASE_READINESS.md`) | Ongoing alongside active slices |

No further product step is selected. Later slice-19 work and other proposals
require a separate explicit cruise update. Existing holds and parallel
release-readiness requirements remain unchanged.

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
The separate [single-run full-text adapter](FULL_TEXT_SYNTHESIS.md) now feeds
saved machine findings into the shared hierarchy within its frozen bounds.

## Landed slice 18 and its limits

[Events and assertions](EVIDENCE_ASSERTIONS.md) preserve typed entity roles,
raw/uncertain dates, supporting and competing originals, and explicit reviewer
status and corrections. Entity detail and paginated chronology expose the
records. Shared names, co-mentions and speaker clusters do not establish identity
or relationships. This manual workflow does not add automatic relationship
inference or entity-to-Report compilation.

<a id="active-implementation-slice-19-first-single-run-adapter"></a>

## Landed slice 19: first single-run adapter and its limits

The [first adapter](FULL_TEXT_SYNTHESIS.md) accepts one terminal full-text run,
its complete criterion and frozen authorized source population. Its versioned
receipt retains original locators, coverage, omissions and human-decision
revisions. Original passages supply evidence; rationales and earlier summaries
do not substitute for them.

Admission retains at most 48 candidates and explicitly omits complete originals
over 6,000 characters. Aggregate original-scan limits refuse incomplete validation;
existing generation bounds remain unchanged. Source, source-set, access, ledger
and worker-attempt changes fence admission, recovery and saved output. Human
decisions remain frozen context, separate from evidence.

The terminal-review action reuses the hierarchy inspector and direct JSON,
Markdown and Word exports. Report copy/compilation remains unsupported for this
adapter. The [dated receipt](FULL_TEXT_SYNTHESIS_ACCEPTANCE_2026-09-12.md)
records 24-original support and contradiction, explicit omissions, keyboard
recovery, durable charges, complete-runtime restore and matching-reader rollback.
The model result retains its explicit evaluation-setting qualification.

Only this first substep is Done. Multiple-run aggregation, new questions,
adjustable capacity, entity-to-Report integration, background/memory,
production imports, held Mac integration and deployment remain outside it.

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
- [FULL_TEXT_SYNTHESIS.md](FULL_TEXT_SYNTHESIS.md)
- [FULL_TEXT_SYNTHESIS_ACCEPTANCE_2026-09-12.md](FULL_TEXT_SYNTHESIS_ACCEPTANCE_2026-09-12.md)
- [RELEASE_READINESS.md](RELEASE_READINESS.md)
- [CONTRIBUTOR_BACKLOG.md](CONTRIBUTOR_BACKLOG.md)
