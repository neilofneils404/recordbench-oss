# Portable RecordBench product slices

The [product north star](../PRODUCT_NORTH_STAR.md) governs product direction;
the [assessment](../PRODUCT_DIRECTION_2026-09-12.md) records gaps and delivery
stages, and the cruise below owns the active implementation order.

Status: implementation briefs. Binding execution order is the
[exit-alpha cruise](../EXIT_ALPHA_CRUISE.md); consult its active step.
Findings checked September 8, 2026 against upstream `main` at
`26f5ece14871ba9312c9aeaf87d42b47edff3022` are a dated checkout note.
Live slice status is the cruise file and each brief's Status line. The
upstream hash was read from the remote and matched the locally available
remote-tracking ref.

Implementation targets portable product contracts and supported deployment
profiles. A contributor workstation is a development host, not a resource ceiling
or evidence of production scale. Local checks, Linux CI, PostgreSQL execution,
clean installation, and larger-corpus acceptance remain distinct evidence.

The product needs two connected improvements: a person must be able to install
and administer it, and a reviewer must be able to move from reliable search to
substantial, source-supported work product. Raising retrieval limits alone will
not deliver the second outcome.

Each linked file is an independently reviewable implementation brief. Build
the shared behavior in this OSS repository, then validate it on applicable
deployment profiles. Host-specific launchers may adapt the shared contract;
they must not become the only place where product behavior is implemented.

## Buildable queue

IDs identify work, not an obligation to execute everything in numeric order.
[Exit-alpha cruise](../EXIT_ALPHA_CRUISE.md) is the binding execution order:
consult its Next row. The briefs remain the implementation specifications;
the cruise document takes precedence over historical sequencing below.

On the verified slice-13 `main` snapshot
(`c1ada89bf15ea8f61906de3c62202da4d98e279f`): slices **01–07**,
**10–15** are implemented, including installer handoff (02),
first-run team setup (03), reusable team groups (06), adaptive investigation
(11), all-extracted-text review (12), and cited hierarchical synthesis (13). Slice **00** has the synthetic corpus
on `main`; PostgreSQL search-job acceptance remains pending. Slice **08** has
the exact-result service on `main`; real PostgreSQL indexed acceptance remains
pending. Slice **09** has proximity on `main`; wildcards and field filters
remain. Hierarchy (**13**) landed in [#73](https://github.com/neilofneils404/recordbench-oss/pull/73).
The entity workspace slices (**16–18**) remain proposed. The cruise selects
active work, including sequencing of remaining 00/08 acceptance and 09 operators. The report's People/Places/Things format does not claim to
implement the persistent entity workspace or identity resolution.

Implementation PR inventory recorded September 8 (historical status; see
[the September 9 selection](../SELECTED_ACCEPTANCE_2026-09-09.md) and live PR state):

| PR | User outcome | Slices |
| --- | --- | --- |
| [#36](https://github.com/neilofneils404/recordbench-oss/pull/36) | Defined exact grammar and known-answer corpus | 00, 07 |
| [#38](https://github.com/neilofneils404/recordbench-oss/pull/38) | Retain findings, gaps, and human decisions in Reports | 14 |
| [#39](https://github.com/neilofneils404/recordbench-oss/pull/39) | Actionable, non-writing installer prerequisites | 01 |
| [#40](https://github.com/neilofneils404/recordbench-oss/pull/40) | Visible investigation budgets and coverage accounting | 10 |
| [#41](https://github.com/neilofneils404/recordbench-oss/pull/41) | Shared local account lifecycle and session revocation | 04 |
| [#42](https://github.com/neilofneils404/recordbench-oss/pull/42) | Complete exact result browsing with guided search | 08 |
| [#43](https://github.com/neilofneils404/recordbench-oss/pull/43) | Browser People administration and first-use entry | 05 |
| [#44](https://github.com/neilofneils404/recordbench-oss/pull/44) | Automatically compile selected saved work into usable drafts | 15 |
| [#45](https://github.com/neilofneils404/recordbench-oss/pull/45) | Nearby words/phrases with guided proximity controls | 09, proximity family |

[CI candidate isolation #37](https://github.com/neilofneils404/recordbench-oss/pull/37)
is a validation dependency, not a product slice. It inspects intended ancestry
and actual branch metadata independently of unrelated fetched branches.

The September 8 PR inventory is historical. Live OSS status is the cruise file
and each brief's Status line. A completed slice is not evidence that a
downstream deployment has adopted it. Stacked PRs include their prerequisites
on the branch and remain testable before merging. The intended Linux deployment
host should validate a combined candidate in a separate synthetic checkout and
installation before deployment-sensitive changes are accepted.

| ID | Slice | Depends on |
| --- | --- | --- |
| [00](00-synthetic-acceptance-corpus.md) | A small shared corpus with known expected results | None; PostgreSQL job pending |
| [01](01-install-prerequisites.md) | Explain and resolve installation prerequisites | None |
| [02](02-install-handoff-and-recovery.md) | Reach first login and resume interrupted installation | 01 |
| [03](03-first-run-onboarding.md) | Guide the first administrator through setup | 02 |
| [04](04-local-account-lifecycle.md) | A shared account write and revocation service | None |
| [05](05-browser-account-management.md) | Create and manage local accounts in the browser | 04 |
| [06](06-team-groups.md) | Reusable groups with explicit matter access | 04, 05 |
| [07](07-exact-search-grammar.md) | Parse strict Boolean queries consistently | 00 |
| [08](08-complete-exact-search.md) | Browse every exact match with reproducible scope | 07; PostgreSQL adapter pending |
| [09](09-advanced-search.md) | Add proximity, wildcard, and field operators | 08; proximity on main; wildcards and fields remain |
| [10](10-review-budget-visibility.md) | Make retrieval and synthesis limits explicit | None |
| [11](11-evidence-driven-investigation.md) | Follow evidence with useful additional searches | 00, 10 |
| [12](12-full-text-review-coverage.md) | Process every extracted unit in a frozen population | 00, 10 |
| [13](13-hierarchical-synthesis.md) | Synthesize findings beyond a 12-passage bottleneck | 11 or 12 |
| [14](14-report-review-basis.md) | Preserve investigation gaps and coverage in Reports | None |
| [15](15-purposeful-report-outlines.md) | Automatically compile useful reports from saved review | 14; integrates 13 |
| [16](16-entity-workspace.md) | First-class People, Places, and Things with mentions | 12; product UI after deeper review |
| [17](17-entity-extraction.md) | Extract and reconcile more than title-based names | 16 |
| [18](18-evidence-backed-relationships.md) | Connect entities, events, and conflicting accounts | 13, 17 |

Historical starting batch (superseded by the cruise order): 00, 01, 07, 10, and 14. These establish known
results, reduce install confusion, define exact-search semantics, expose real
review limits, and stop losing useful context when making Reports. Slices 01–07,
10–15 are on the dated baseline above. Entity work follows that review
foundation; consult the cruise for the active step and later scheduling.

## Evidence and current answers

See [findings and validation](FINDINGS.md) for the September 8 checkout
observations, reproduction examples, and the limits of those checks.

* Installation has preflight, resumable handoff, and first-administrator team
  setup. People and team groups are on `main`. Clean-host adoption remains
  operator evidence.
* Exact search is a separate complete-result path with Boolean grammar and
  proximity. The ranked answer retriever is still not that exact set.
  PostgreSQL indexed exact-search acceptance remains pending. Wildcards and
  field filters remain unsupported.
* Investigations follow evidence within a budget. Saved findings now feed issue-level and
  matter-level synthesis with original citations and explicit partial results;
  each generation call retains its existing input limit. Selected-passage source checks remain; **Review
  all extracted text** covers every eligible unit in a frozen population.
* Reports preserve review basis and can compile saved work into drafts.
  Hierarchical cited synthesis landed as slice 13; its versioned checkpoints
  and model-evaluation limits are documented in [HIERARCHICAL_SYNTHESIS.md](../HIERARCHICAL_SYNTHESIS.md).
* People/place/date candidates exist, but the persistent entity workspace
  (16–18) is still proposed.

## Proposed extension

[19: full-text synthesis](19-full-text-synthesis.md) connects one terminal
full-text review to cited synthesis. It is proposed, not scheduled, and does
not displace the active entity sequence.

## Definition of done for every slice

1. State the visible user outcome and preserve synthetic regression evidence.
2. Keep authorization, source/version citations, machine/human distinctions,
   offline operation, and explicit incomplete states intact.
3. Update applicable operator and user documentation. Reconcile claims across
   README, help text, exports, and API behavior.
4. Run applicable unit/integration checks. Browser behavior needs browser
   acceptance. PostgreSQL behavior needs PostgreSQL execution; a fallback or
   mock passing is insufficient. Installer claims need a clean target host.
5. Persistent schema/storage changes need backup and clean-restore evidence,
   migration/rollback behavior, and review of mirrored migration copies.
6. Model changes need pinned revision, license record, offline readiness, and
   representative evaluation. A stronger model is not assumed to fix coverage.
7. Apply the repository's publication, review, CI, and release gates. A completed
   slice is not evidence that a downstream deployment has adopted it.

Do not add private deployment examples or material to these briefs or tests.
Before coding, refresh upstream and inspect open work for overlap. Existing
schema, export, identity, and retention contracts take precedence over guesses
based on a stale checkout.
