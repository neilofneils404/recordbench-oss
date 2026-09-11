# Findings behind the portable product slices

Checked September 11, 2026 against upstream `main` at
`8d23ceeefbdf9f89cd4deba760126ea45e2cf188`. These are code-level findings and
bounded synthetic observations, not a deployed-system audit or a fresh-host
installation qualification. Source locations below refer to the original
September 8 checkout at `26f5ece14871ba9312c9aeaf87d42b47edff3022` unless a
later note says otherwise.

Since that checkout, live implementation status lives in the
[exit-alpha cruise](../EXIT_ALPHA_CRUISE.md) and [slice index](README.md).
On current `main`, reusable team groups (**06**), evidence-driven investigation
(**11**), and full-text review (**12**) exist; hierarchical synthesis (**13**)
is Next.

## Installation and onboarding

The installer exists and creates the first local administrator through
`accounts init`; it is incorrect to describe initial administrator creation as
absent. The adoption gap is the surrounding prerequisite and first-team journey.
`docs/INSTALL.md` requires a dedicated non-root account, storage ownership,
Docker/Compose, TLS/authentication decisions, optional model/GPU staging, and
operator acceptance. That is substantial work for an unfamiliar person.

Account management is described as a tools-container CLI operation in
`docs/AUTHENTICATION.md`. `admin_cli.py` implements init/add/password/list.
`LocalAccountSettings` loads the file into memory, and `compose.yaml` mounts
secrets read-only in the application. New account UI therefore needs a real
write/refresh/revocation design, not just forms.

`templates/workbench_admin.html` labels principals as domain users and says
roles are managed by AD security groups without selecting copy by auth mode.
`templates/workbench_setup.html` is Sources/matter setup, not first-run system
onboarding. Matter membership UI exists for known principals. Application team
groups with their own matter grants were not found in the inspected September 8
paths. On current `main` they exist as slice **06**; see
[team groups](../TEAM_GROUPS.md).

Implementation: [01](01-install-prerequisites.md),
[02](02-install-handoff-and-recovery.md), [03](03-first-run-onboarding.md),
[04](04-local-account-lifecycle.md), [05](05-browser-account-management.md),
and [06](06-team-groups.md).

## Boolean and exact search

Three relevant paths have different purposes and semantics:

| Path | Observed behavior | Consequence |
| --- | --- | --- |
| Sources catalog filter | `_source_catalog_filter` uses a substring of its search key | This is not the same as a content query with Boolean operators |
| CPU workbench retrieval | `InMemoryHybridBackend.lexical` scores any shared tokens; deterministic dense fallback also requires overlap | AND, phrase, and exclusion syntax is not enforced |
| Learned retrieval | PostgreSQL lexical FTS plus pgvector, fused and reranked | A lexical constraint is not a constraint on all fused results |

`PostgresHybridBackend.lexical` uses `websearch_to_tsquery('english', ...)` on
chunk vectors. PostgreSQL documents quoted phrases, `or`, and dash negation;
other punctuation is ignored, and this function does not accept prefix labels
or the full `tsquery` syntax. It normalizes/stems according to the text-search
configuration. See the official
[PostgreSQL 17 search-control documentation](https://www.postgresql.org/docs/17/textsearch-controls.html).
That is not a product-level Boolean grammar with parentheses, proximity,
wildcards, and field semantics.

`HybridRetriever.search` unions the lexical and dense lanes. In learned mode,
semantic-only candidates can remain when dense/rerank scores clear 0.72/0.80.
There is no post-fusion Boolean predicate enforcing a lexical exclusion.
Additionally, lexical matching occurs per chunk, so document-level AND/NOT
across different pages needs a separately defined implementation.

Run the [synthetic probe](probe_search.py) from the repository root:

```bash
PYTHONPATH=src python docs/product-slices/probe_search.py
```

Observed CPU fallback examples used four synthetic texts: `red bicycle`,
`blue bicycle`, `red truck`, and `the bicycle is not blue`.

* `red AND bicycle` returned all four texts.
* `bicycle -blue` returned blue-containing texts as well as `red bicycle`.
* `"red bicycle"` returned nonphrase matches.
* A controlled split-lane backend demonstrated that a semantic-only
  blue-containing candidate can survive even when the lexical lane omits it.
* A request for 30 results from 50 matching candidates returned 20.

The split-lane experiment tests the production fusion logic with controlled
backend/reranker scores. It is not a real PostgreSQL or learned-model execution.
The script reports observations; its current outputs are defects to address,
not acceptance expectations to preserve.

Implementation: [07](07-exact-search-grammar.md),
[08](08-complete-exact-search.md), [09](09-advanced-search.md),
and the explicit limit contract in [10](10-review-budget-visibility.md).

## Deep review

The table records bounds observed at the September 8 checkout. On current
`main`, slice **11** follows evidence with additional searches inside a budget,
and slice **12** reviews every eligible extracted unit. Final synthesis is
still at most 12 passages until **13**.

| Stage | Observed bound or behavior | Source |
| --- | --- | --- |
| Default investigation plan | Up to five preset question variants | `workbench.py::_research_plan` |
| Lexical and dense lanes | At most 100 candidates per lane | `review_bench_v2.py::HybridRetriever` |
| Reranking | At most 40 fused candidates | Same class |
| Returned candidates | At most 20, even when caller requests 30 | `HybridRetriever.search` |
| Per-pass selected evidence | At most 12 passages | `_process_research_job` |
| Evidence ledger | Capacity 72; five default passes can contribute at most 60 unique selected passages before overlap | `_process_research_job` |
| Final synthesis | At most 12 reselected passages; saved pass narratives are not themselves synthesized as a structured findings set | `_process_research_job` |
| Generator evidence | 12 items, 6,000 characters per item, 48,000 characters total | `generation.py` |
| Standard answer output | 1,200 output tokens | `generation.py` HTTP generator request |
| Every-source classification | At most 12 selected passages within each frozen source | `_process_review_decision` |

These are selection/resource boundaries, not proofs of recall. The stored
candidate count accumulates returned passages across passes and is not a unique
document count. Modality-specific supplemental searches can add work; five
default plan passes should not be described as an absolute total of all internal
retrieval calls.

The every-source path correctly keeps a no-match source unresolved instead of
equating zero hits with exclusion. At that checkout, its unit coverage still
depended on selecting passages, so a completed source population was not a
completed all-page read. On current `main`, **Review all extracted text**
covers every eligible unit in a frozen population (slice **12**); selected-passage
screening remains a separate mode, and cross-source hierarchical synthesis
remains **13**.

Implementation: [10](10-review-budget-visibility.md),
[11](11-evidence-driven-investigation.md), [12](12-full-text-review-coverage.md),
and [13](13-hierarchical-synthesis.md). Slices **11** and **12** exist on
current `main`; **13** remains Next. The remaining gap is cited hierarchical
synthesis, not an unbounded larger prompt.

## Why Reports can feel insubstantial

Reports currently assemble text and cited material. They do not automatically
turn a purpose into a well-developed analysis. `research_to_report` stores the
final summary and citations in one section. It does not turn the saved gaps,
passes, and coverage into report sections. `full_review_to_report` mainly stores
the criterion, counts, validation count, and citations from machine-included
decisions. Its cited-detail list stops at 100 entries.

The report's evidentiary appendix can therefore be longer than its reasoning,
while the actual answer remains constrained by the final 12-passage packet and
short answer output. This is an inference from the conversion and generation
paths; no private or real user report was reviewed.

Current upstream already includes saved Reports in complete matter bundles:
`docs/REPORT_EXPORTS.md`, `reports_for_final_bundle`, and
`tests/test_reports_bundle.py` establish that implementation. Do not repeat the
older checkout's claim that saved Reports are omitted. Inclusion/export repair
and analytical usefulness are separate work.

At inspection, open [PR #32](https://github.com/neilofneils404/recordbench-oss/pull/32)
covered final-export readiness and links to Reports needing repair. Recheck its
state and avoid overlapping that work. These slices address content and review
basis: [14](14-report-review-basis.md) and [15](15-purposeful-report-outlines.md).

## People, Places, and Things

`suggest_notebook_references` uses title-based person patterns, selected place
patterns, and dates. It examines at most 2,500 units with at most 6,000 characters
per unit and creates at most 75 new suggestions by default. Label-based
deduplication avoids repeated notes, but does not build all mentions of an
entity. `matter_analysis.py` also has a 2,500-unit and 150-finding bound.

The review map is a Work product subpage and sends entity management to notes.
Its shared-reference comparisons and simple negation comparisons are candidate
leads, not a mature entity-resolution or relationship system. Moving the
navigation alone would leave the data/coverage limitations intact.

Implementation follows deeper review: [16](16-entity-workspace.md),
[17](17-entity-extraction.md), and [18](18-evidence-backed-relationships.md).
Retain what already works: exact support, suggested/confirmed/disputed states,
and the ability for a human to correct machine output.

## External assessment: what is and is not established

A supplied external assessment expressly reviewed README/repository structure,
not the complete code. Its useful observations align with real components:
received-byte matching, intake receipts, malware scanning, timestamped media,
hybrid retrieval, cited answers, and encrypted backup tooling.

Two claims need narrower language. Exact received-byte groups preserve separate
source occurrences; they do not themselves perform deduplication or establish
that one review covers every occurrence. Intake receipts record selection and
transfer/processing states; that alone does not establish complete custody or
security compliance. See `docs/EXACT_BYTE_MATCHES.md` and
`docs/INTAKE_RECEIPTS.md`.

No evidence about another system's code, workload, operating history, or
comparative quality was supplied for independent verification. The assessment
therefore cannot establish that another system is more hardened or scales
better. Hosting location alone does not establish those outcomes. No private
system description or attached document is copied into this repository.

## Validation performed and remaining limits

* Inspected current upstream installer/authentication, retrieval/orchestration,
  generation, report conversion/export, notebook/analysis, and source UI paths.
* Ran the bounded search probes described above.
* Ran six existing focused suites: retrieval v2, research/full review, Report
  conflicts, Report bundles, OSS installer, and identity/membership. Result:
  113 passed, 11 failed on this development host.
* Three failures involved the Linux-oriented PDF helper: direct reproduction
  showed `resource.setrlimit(RLIMIT_AS, ...)` raising `ValueError` before
  extraction on the host. This is not a reason to remove parser containment.
* Other failures initially returned insufficient storage: the configured
  default reserve is 100 GiB. Reran the research and bundle suites with reserve
  zero only in the isolated synthetic test process: 40 passed, one media-upload
  test still returned HTTP 400. That remaining media failure was not diagnosed
  as an application defect in this audit.
* No production settings were changed. No clean-host install, real PostgreSQL
  integration run, real-model quality evaluation, full browser audit, or
  million-document benchmark was performed here.
* On the documentation branch, the existing OSS installer, identity/membership,
  and Report-conflict suites passed all 64 tests. The saved search probe ran
  against the checked upstream code and reproduced the documented observations.

These checks support the specific findings. They are not a green release gate.
Slice 00 establishes reusable product examples; each implementation must add
the applicable target-environment and end-to-end evidence before completion.
