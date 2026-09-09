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

## Durable background compilation

`ReportCompilationJobs` stores only compilation intent (type, topic, selected
record or collection identifiers), its input fingerprint, status, and final
report identifier in migration `0027_report_compilation.sql`. The coordinator
performs model work outside HTTP requests. `CompilationJobPolicy` controls active
per-actor/global admission, selection size, lease duration, and interrupted-worker
attempts. Database write transactions serialize admission and claims across
independent worker processes; only expired leases are recovered. An active
worker's random lease token fences older workers, including a worker returning
from model generation after its lease expired.

Workers persist the initial resolved fingerprint before model work. The flow
re-resolves current material and enters `jobs.complete(job, builder,
fingerprint=draft.fingerprint)` while holding the source guard. Completion checks
current authorization, the live lease token, cancellation, the input fingerprint,
and the resulting report's matter. The builder must use the transaction already
owned by `complete`: call `WorkspaceStore.create_report_from_sections` with
`transaction_owned=True`. It must not begin/commit a transaction or call a model.
Report creation and the job's successful result link then commit together or
roll back together. A stale worker cannot create a second report.

The application must register the mirrored migration in its migration list,
include queued/running compilation jobs in its active-work closure inventory,
and close the coordinator before closing workspace storage. Matter deletion
cascades the intent rows. Revoked access and non-active matters prevent admission,
claiming, and completion. A user's request key is bound to its original kind,
topic, and selection; reusing it with different inputs fails explicitly.

Cancellation is cooperative between model calls, with another check before
atomic save. Heartbeats extend only live owned leases. Graceful shutdown stops
new claims and fences/requeues current intent; an outstanding model request may
finish afterward but cannot save its result. Repeated expired leases eventually
produce a failed job requiring explicit retry. Leases use UTC epoch timestamps,
so multi-worker hosts sharing the control database need synchronized clocks.
No restart blindly resets all running jobs.

The queue's synthetic regressions use two independent processes, crash/expiry and
stale-token attempts, delayed heartbeats, cancellation/retry, denied matter access,
admission pressure, rollback after report creation, and a SQLite online backup
restored into a clean workspace. Restore preserves the original live lease until
expiry, then admits one replacement claim; `PRAGMA integrity_check` remains clean.

## Relevance of human review

Topic reports classify saved human notes and recorded gaps before selecting them
for the report. The existing grounded answer service receives these as attributed
review records, including unsourced notes. The compiler consumes only allowed
record identifiers from the classification result: it retains the original human
text, exact citations, author, status, and revision. Classification prose is never
used as a source fact. Related disagreements remain visible; unrelated disputes
are omitted along with unrelated ordinary notes. Source-coverage limits remain a
separate appendix because they qualify the selected work rather than assert a
topic finding.

People/Places/Things reports retain explicit human person/place/thing categories.
Ordinary human notes are semantically classified using the same record-selection
protocol; notes that cannot be classified appear in an explicit review appendix.
Similar names still do not establish the same identity. Classification shares the
report's model-call and context budgets with source synthesis. The durable report
basis includes checked, selected, unchecked, and omitted note counts and text
truncation; it never treats a budget omission as a negative relevance finding.

If no model is available, a multi-item topic compilation asks the reviewer to
retry or select one relevant saved item. A single-item fallback is visibly labeled
unfiltered, with topic relevance not checked. Plain-language coverage is visible
in the draft; technical counters remain after the `Review basis:` delimiter.

The `model_calls` counter and call policy count verified answer-service calls.
The existing generation service can make one additional source-close repair
request inside each call; this is part of its established verification contract.
It is not a count of raw model-server requests. Coverage records this unit
explicitly rather than presenting repair requests as unbounded or nonexistent.
