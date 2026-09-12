# Product assessment and delivery plan: September 12, 2026

## Scope and evidence

This assessment reads OSS `main` at
`3c4b1e2214b88d605e363556e968c089319fad66`. It is a code and documentation
assessment, not a fresh browser audit, model evaluation, or deployment test.
The [north star](PRODUCT_NORTH_STAR.md) records the intended user experience.
No private deployment material informed this document.

The foundation is substantial: accountable folder intake, source browsing,
separate exact search, full extracted-text review, saved investigations,
hierarchical synthesis, reports, and team access already exist. The main product
gap is connecting these into a coherent matter workspace with persistent
knowledge and genuinely scalable collection review.

## Current position

| Need | Evidence in this revision | Remaining gap |
| --- | --- | --- |
| Bring in discovery folders | [Selection receipts](INTAKE_RECEIPTS.md), [folder navigation](SOURCE_FOLDER_NAVIGATION.md), and [distinct occurrences](UPLOAD_OCCURRENCES.md) retain selected items, paths, and receipt outcomes. | Arbitrary folder drag/drop and production fidelity need explicit browser acceptance. Empty folders are absent from current receipts. Load-file/native-image-text families and complete email attachments remain gaps. |
| Excellent human review | Sources, playback/transcript views, review decisions, shared notes, exact results, and Reports exist. | No first-class-experience claim follows from code presence. Validate a continuous keyboard and browser journey, including manual review with unavailable AI, interrupted work, and return to the same search context. |
| Find every exact match | [Exact result service](EXACT_SEARCH_RESULTS.md) separates complete-result enumeration from ranking; Boolean grammar and proximity exist. | PostgreSQL exact-search adapter/acceptance and wildcard/field operators remain outstanding. The seven-test PostgreSQL CI lane does not establish exact-search parity. |
| Thorough model review | [Full-text review](FULL_TEXT_REVIEW.md) has frozen populations, canonical ranges, checkpointing, gaps, and durable accounting. | Defaults are 1,000 sources, 20,000 units, 10 million characters, and 5,000 calls per run, each independently limiting. This is not a 10,000-PDF or million-record acceptance receipt. |
| Substantial sourced answers | [Hierarchical synthesis](HIERARCHICAL_SYNTHESIS.md) now consumes saved investigation findings in issue and matter stages, retaining originals and competing accounts. | Search remains bounded to 72 selected units; synthesis has group, call, character, and time limits. It does not consume full-text run findings. The old statement that every final investigation uses only 12 passages is stale for new hierarchy-enabled plans. |
| Entities and chronology | Notebook suggestions, review maps, dates, and report formats exist. | [16](product-slices/16-entity-workspace.md), [17](product-slices/17-entity-extraction.md), and [18](product-slices/18-evidence-backed-relationships.md) still define persistent entities, all supported mentions, alias reconciliation, and events. Note labels are not an entity index. |
| Matter context and memory | Conversations, notes, investigations, human decisions, and reports persist. | There is no unified inspectable matter-memory contract, nor a dedicated background-material workflow that binds origin and inclusion choices through retrieval and exports. Durable/reopenable matters remain separate lifecycle work. |
| Hardware and model choice | [Model portfolio](MODELS.md) and [installation](INSTALL.md) provide pinned candidates, GPU placement, preflight, storage selection, staging, and resumable setup. | Universal model/runtime installation and datacenter scaling are goals. The hierarchy's small native-model receipt uses evaluation settings that do not qualify default application requests or other topologies. |
| Maintainable core | Focused modules already exist for exact search, full-text review, hierarchy, reports, accounts, and provenance. | `workbench.py` is 15,215 lines and `workspace_store.py` is 11,311 at this revision. Coordination and persistence remain concentrated; module extraction needs preserved transaction and authorization boundaries. |

## Reconcile the execution documents

[PR #74](https://github.com/neilofneils404/recordbench-oss/pull/74) merged on
September 12 at the assessed revision. Its landing receipt marks 13 Done and
16–18 Next, and dates superseded findings. This alignment preserves those
completed states and makes 16 the first implementation within that sequence.

The product-slice index and contributor entry points should link to the binding
cruise rather than repeat a Next number. Historical acceptance documents remain
dated evidence. Current behavior belongs in feature contracts, execution state
in the cruise, product intent in the north star, and production qualification in
release readiness. Updating one should trigger a check of linked claims.

## Proposed delivery sequence

This is a proposed sequence for maintainer planning, not a second binding queue.
Before implementing a new step, name its narrow scope in the cruise, inspect
open work, and apply the existing contribution and review gates.

1. **Build the cast on the landed hierarchy.** The hierarchy handoff is
   complete. Implement 16 as a small manual entity/mention workspace
   before adding extraction (17) and assertions/events (18). The first journey
   is: create a person, attach two exact passages, record an alias proposal,
   revisit both mentions, and preserve a same-name person separately. Require
   keyboard/browser, authorization, source-change, migration, and restore evidence.
2. **Connect full-text findings to synthesis.** Use the scoped
   [ledger-to-synthesis brief](product-slices/19-full-text-synthesis.md). First
   prove one terminal run and one question through the existing hierarchy with
   explicit omissions. This connects existing coverage work to useful work
   product before expanding its capacity. It is not yet scheduled by the cruise.
3. **Add matter background and inspectable memory.** Start with source roles
   for discovery versus background and a reviewer-owned matter objective.
   Preserve original identity, authority to change roles, and recorded query
   inclusion choices. Then add a memory view over existing saved work with
   provenance, revisions, correction/exclusion, and unresolved questions.
   Do not create a second untraceable fact store or silently treat allegations
   and user assertions as established facts. Draft lifecycle/storage contracts
   before implementation; exercise closure, export, and restore.
4. **Make complete intake and exact retrieval operational.** Give load-file
   import, attachment-family intake, and missing exact operators separate briefs.
   Validate production identifiers, hierarchy, parents/children, originals,
   duplicates, interrupted import, and every skipped member. Finish indexed
   exact-search acceptance with known-answer parity and complete pagination.
5. **Grow collection capacity and model portability with evidence.** Add
   independently reviewable scheduling, partitioning, aggregation, provider
   capability, and operator-policy increments. Preserve global coverage across
   partitions, source versions, fair multi-matter admission, durable spend,
   cancellation, and resumability. Test a known-answer 10,000-document synthetic
   collection before setting higher targets. Million-record and multi-node
   claims require their own receipts; raising a constant is not that work.

Manual-review usability, accessibility, installation recovery, and release
readiness belong alongside every increment. Existing cruise holds, including
the Mac path and reopenable matters, are not implicitly lifted by this proposal.

## The first reliable core release

A team should be able to install a declared supported profile from the public
playbook, create and authorize a matter, bring in a documented folder shape,
understand every intake exception, browse and search, conduct bounded review,
verify and save findings, return to its work, export it, and recover after an
interruption. State supported formats and actual corpus/resource limits.

That is a coherent release boundary while broader production imports, flexible
memory, and datacenter scale develop. It still requires every applicable
[supported-release requirement](RELEASE_READINESS.md), including unfamiliar
operator installation, model/license evidence, security and browser acceptance,
and backup/restore/update/rollback. A completed cruise feature row alone does
not establish beta or confidential-casework readiness.

## How each increment earns acceptance

Use a synthetic case with dispersed support, a contradiction late in the
collection, two same-name people, an alias, an uncertain date, an unreadable
source, and an attachment that needs processing. Add background material whose
assertions disagree with discovery. Specify expected results before running.

Record intake completeness, exact-match parity, source/range coverage, relevant
mention and finding recall, false claims and false identity merges, citation
resolution, and preserved human decisions separately. Record elapsed time,
peak resources, concurrent matters, interruption/restart, and actual hardware
for capacity claims. Do not combine these into a single reassuring score.

For each visible workflow, verify the full path from entry through source
inspection, save, reopen, and export. Capture keyboard use, reflow, error
recovery, loading/empty states, and whether a new reviewer understands what was
and was not processed. Use the same path with AI unavailable where supported.
