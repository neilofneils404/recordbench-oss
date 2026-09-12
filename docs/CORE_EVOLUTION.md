# Evolving the RecordBench core

Status: architectural direction; no runtime or storage change in this document.
The [north star](PRODUCT_NORTH_STAR.md) defines why these boundaries matter.
[Architecture](ARCHITECTURE.md) describes the implementation that exists today.

## Keep the application in charge

Build a modular application with separately deployable model/media workers where
needed. A stable core need not start as a plugin marketplace or distributed
rewrite. Local operation should remain straightforward; moving workers onto
more hardware must not create a second authority for permissions or findings.

| Boundary | Owns | Extension rule |
| --- | --- | --- |
| Matter and access | Matter identity, memberships, policy, source-role scope, lifecycle | Every read/write/job rechecks access; modules cannot grant themselves scope. |
| Sources and provenance | Received occurrences, versions, extraction identity, locators, original support | Preserve production relationships and stable references; summaries never replace originals. |
| Work and resources | Durable job state, attempt fencing, admission, cancellation, accounting | Providers run admitted work; retries cannot refund charged calls or overwrite newer attempts. |
| Human knowledge | Notes, decisions, entity reconciliation, memory selections, saved work | Machine proposals never overwrite reviewer decisions; mutations use revision checks. |
| Retention and portability | Export contracts, closure, deletion, backup/restore, audit | New persistent records join the same lifecycle and restoration boundary. |

Intake, exact/semantic search, document/media review, investigation, full-text
analysis, synthesis, entities, and report compilation are feature modules using
those contracts. Runtime/model adapters advertise capabilities and resource
requirements while retaining artifact identity and provenance. A capability
advertisement does not replace acceptance of the selected model/runtime pair.

## Extract one boundary at a time

1. Choose the next authorized product slice and identify the smallest cohesive
   service it touches. Write the visible behavior and transaction invariants
   before moving code. Existing focused modules are the starting point.
2. Capture regressions at the existing public workflow boundary, including
   cross-matter denial, concurrent changes, cancellation/recovery, stale source
   support, and human edits where relevant.
3. Extract orchestration from `workbench.py` into that service. Keep routes and
   templates as callers. Inject narrow dependencies; do not pass the entire
   application into a new file and call the coupling solved.
4. Extract the relevant repository operations from `workspace_store.py` behind
   an explicit unit-of-work boundary. Keep authorization checks, source-scope
   validation, and final save atomic where they are atomic today. Do not introduce
   independent connections that silently split a protected transaction.
5. Keep legacy entry points delegating during migration. Prove persisted jobs,
   prior saved work, exports, and recovery remain compatible before removing
   old paths. If storage changes, supply migration and clean-restore evidence.
6. Keep behavior changes and mechanical movement separately reviewable. No
   arbitrary file-size target justifies a risky rewrite during feature delivery.

For slice 16, a small entity service and repository should own entity/mention
operations, with explicit actor/matter authority and shared transaction scope.
Routes should not acquire another large block of entity persistence SQL. The
full-text synthesis adapter should reuse `hierarchical_synthesis.py` through a
validated input contract; it should not copy the synthesis engine.

## Evidence that modularity helped

A module can be exercised through a narrow interface without constructing the
whole web application. Its dependencies and transaction owner are explicit. A
model adapter can change without rewriting evidence or retention semantics.
Existing saved work survives the change. Integration and recovery checks still
exercise the real composition. Smaller files alone are not success.
