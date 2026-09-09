# Compiling saved work into a report

`report_compilation.py` turns a selection of saved evidence-backed work and human
review into a complete editable report draft. Its portable material protocol
includes the original material identity, revision, author, review status, exact
source citations, and optional date/category metadata. The compiler does not read
live storage or resolve source references; the caller must provide current,
validated snapshots.

Timeline compilation asks the existing grounded answer service for dated events
and competing accounts. It sorts only unqualified, valid ISO dates; approximate,
relative, conflicting, and otherwise unresolved date expressions retain their
original wording. People/Places/Things compilation uses three semantic model
queries and saves separate source-linked mention statements. Similar names are
not collapsed into a single identity. Topic compilation asks for findings specific
to the supplied topic and omits machine material that did not support an accepted
finding. Unsupported model citation identifiers never become report citations.

Each model request uses original cited source passages through the existing
independently verified generation service. The compiler attaches only the source
references used by each accepted claim. Human notes remain human-authored review;
disputed and unfinished decisions stay in separate visible sections. Saved gaps
and coverage limits are retained as attributed prior review, not new source
findings. Material identities and revisions appear after the `Review basis:`
delimiter so a reader can expand that detail while exports retain it.

When no model is available, the compiler explicitly arranges the selected saved
work without claiming a new semantic synthesis. Unsourced machine statements are
excluded; unsourced human notes are visibly labeled. A selection containing no
supported content fails with an actionable message instead of producing empty
outline sections. This fallback is not an entity-resolution or topic-relevance
engine.

## Integration and concurrency

1. Resolve all selected material and exact citations under the source/workspace
   guard. Include revisions for every contributing human or machine record.
2. Call `compile_report(kind, topic, materials, generator, budget=...)` outside
   those locks. It snapshots inputs before calling the model.
3. Under the guard, resolve the same selection again and recompute
   `compilation_fingerprint(kind, topic, fresh_materials, budget=...)`.
4. If the fingerprint or any reference changed, reject the stale draft. Otherwise
   save every section atomically using the existing report-store transaction.

The fingerprint binds kind, topic, selection order, every selected material and
citation (including omitted material), compilation format, and work budget. It
requires no process-local preview cache and works across workers. The report
sections are ordinary heading/body/citation mappings; structured provenance and
coverage are also available to callers. The original attribution remains in body
text when the report store persists only its standard columns.

## Work budget and validation

`CompilationBudget` defaults to 200 selected materials, 12 model calls, and 200
content sections, with one additional coverage ledger. Callers may choose a
policy appropriate to their server; no behavior depends on macOS or a particular
GPU. Model packet bounds use the existing shared generation contract. The durable
coverage ledger states skipped materials, model calls, unprocessed passages,
rejected claims, unavailable calls, omitted sections, and truncated source text.
These counts describe selected saved work, never an exhaustive matter review.

Synthetic tests cover grounded chronology, uncertain/conflicting dates, separate
same-name mentions, topic relevance, foreign citation rejection, human attribution,
saved gaps, offline labeling, omitted-material budgets, snapshot mutation during
model work, and revision-bound fingerprints. Deployment capacity and model
throughput need separate Linux/GPU validation.
