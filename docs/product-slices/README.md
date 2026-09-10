# Portable RecordBench product slices

Status: implementation briefs with the first changes in review. Findings checked September 8, 2026 against
upstream `main` at `26f5ece14871ba9312c9aeaf87d42b47edff3022`. The upstream hash
was read from the remote and matched the locally available remote-tracking ref.

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
slice **06** is next. The briefs remain the implementation specifications;
the cruise document takes precedence over historical sequencing below.

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

Review and CI completion must be read from each PR; this index does not mark a
change accepted or deployed. Stacked PRs include their prerequisites on the
branch and remain testable before merging. The intended Linux deployment host
should validate a combined candidate in a separate synthetic checkout and
installation before deployment-sensitive changes are accepted. No default-branch
merge is needed for that test.

Installer handoff/onboarding (02/03) and all-extracted-text review (12) are being
implemented separately. Adaptive investigation (11), hierarchy (13), reusable
team groups (06), remaining advanced operators, and the entity workspace and
relationship slices remain proposed. The report's People/Places/Things format
does not claim to implement the persistent entity workspace or identity resolution.

| ID | Slice | Depends on |
| --- | --- | --- |
| [00](00-synthetic-acceptance-corpus.md) | A small shared corpus with known expected results | None |
| [01](01-install-prerequisites.md) | Explain and resolve installation prerequisites | None |
| [02](02-install-handoff-and-recovery.md) | Reach first login and resume interrupted installation | 01 |
| [03](03-first-run-onboarding.md) | Guide the first administrator through setup | 02; integrates 05 and 06 later |
| [04](04-local-account-lifecycle.md) | A shared account write and revocation service | None |
| [05](05-browser-account-management.md) | Create and manage local accounts in the browser | 04 |
| [06](06-team-groups.md) | Reusable groups with explicit matter access | 04, 05 |
| [07](07-exact-search-grammar.md) | Parse strict Boolean queries consistently | 00 |
| [08](08-complete-exact-search.md) | Browse every exact match with reproducible scope | 07 |
| [09](09-advanced-search.md) | Add proximity, wildcard, and field operators | 08; three small follow-ups |
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
review limits, and stop losing useful context when making Reports. Next finish
02-05 and 08, then deepen review through 11-13. Entity work follows that review
foundation, as requested. Group and advanced-search work can proceed once their
own prerequisites are ready.

## Evidence and current answers

See [findings and validation](FINDINGS.md) for observed behavior, reproduction
examples, source pointers, and the limits of the checks performed.

* Installation already has a CLI and initial local administrator creation. It
  still expects substantial operator knowledge and lacks a complete team setup
  journey.
* The browser can add existing principals to a matter. Creating local accounts
  is a separate CLI workflow; reusable application-managed team groups were not
  found in the inspected identity and membership paths.
* Investigation uses five default query variants and a final packet of at most
  12 passages. Every-source checks select passages from each source, not every
  page. These are distinct coverage problems.
* The current hybrid search is not a strict Boolean result set. CPU fallback
  and PostgreSQL lexical semantics differ, and semantic candidates can enter
  the combined results without satisfying a lexical exclusion.
* Reports can preserve edited work and export it. Their usefulness is limited
  by shallow upstream synthesis and minimal conversions, not simply formatting.
* People/place/date candidates exist, but title-based patterns, bounded scans,
  note deduplication, and note-oriented navigation constrain their usefulness.

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
