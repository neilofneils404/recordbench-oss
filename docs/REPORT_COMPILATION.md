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

When no model is available, or every attempted synthesis call is rejected or
unavailable, the compiler explicitly arranges the supported saved source findings
without claiming a new semantic synthesis. Unsourced machine statements are
excluded; unsourced human notes are visibly labeled. A selection containing no
supported content fails with an actionable message instead of producing empty
outline sections. This fallback is not an entity-resolution or topic-relevance
engine.

## Reviewer workflow

Open Reports and choose **Compile saved work**, or choose **Make a report** while
reviewing an AI answer, investigation, source check, or team note. Choose a
Timeline, People/Places/Things report, or Topic brief. Saved team notes and the
latest available AI work provide an editable starting selection. A topic brief
requires a focus; the other formats accept an optional focus.

The request queues durable background work and opens its progress page. Reviewers
can stop it, leave the page, or retry a failed request from Reports. Completion
opens the document as readable prose with source links. **Edit this draft** exposes
section editing and ordering; ordinary prose edits preserve the saved compilation
basis under the same revision check. Word and Markdown exports retain that basis,
human edits, gaps, and source support. Blank documents remain available as an
explicit secondary option.

The default selection is saved review work, not every source in a matter. Work
that changed while compiling causes a visible failure before any report is saved.
Stale or unresolved source support also fails explicitly. Full canonical source
units up to 50,000 characters can be preserved even when the prior notebook showed
only a shorter excerpt; the frozen digest must match. Larger units fail rather
than silently losing the end of their support.

The UI uses the shared server policy, with configurable positive integers
`CASE_INTELLIGENCE_REPORT_MAX_MATERIALS`, `CASE_INTELLIGENCE_REPORT_MAX_MODEL_CALLS`,
`CASE_INTELLIGENCE_REPORT_MAX_SECTIONS`, and `CASE_INTELLIGENCE_REPORT_WORKERS`.
These are capacity controls, not claims about pages reviewed. The selection adapter
accepts at most 20 collections/records, 500 material records, 10,000 references,
and 5 million canonical citation characters counted across repeated occurrences.
It enforces that aggregate while resolving references, before snapshot hashing;
overlarge selections ask the reviewer to narrow the draft. The completed draft
also counts repeated citation text, escaped text and metadata against the shared
10-million-character export capacity before it can be saved. The compiler records
any smaller policy omissions in its coverage section.

`tests/test_guided_reports.py` exercises all three HTTP-to-background-to-document
flows, human editing, exports, idempotent requests, changed inputs, retry,
cancellation, authorization and CSRF. `scripts/browser-accept-compiled-reports.py`
walks the same flow in real Chrome at desktop and 390-pixel widths, saves synthetic
screenshots, and downloads Word and Markdown. Its deterministic source-echo client
validates the product workflow; it is not representative model-quality evidence.

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

Optional focus applies to Timeline and People/Places/Things source prompts and
human-record selection as well as Topic reports. Related disputes remain visible;
unrelated notes are omitted with coverage accounting. Focused multi-item work
requires relevance classification; an offline single-item fallback is labeled
unfiltered. A review-selection claim must cite exactly one distinct allowed
record, so an otherwise supported sentence cannot select an unrelated extra ID.
An entity source passage or review record is fully checked only after all three
category calls complete. Interrupted or unavailable category passes remain explicitly partially
classified, with the original note in the unclassified appendix and category
progress in coverage.

`CompilationMaterial.review_details` carries saved technical review details
separately from user prose and participates in the full snapshot fingerprint.
Every section includes its exact compiler-authored `compilation_basis`; the same
string is appended to its body after `\n\nReview basis:\n` for existing exports.
Readers must use that separately stored basis and verify the exact body suffix;
they must never split on the first matching delimiter in human-authored text.


## Stored provenance and recovery

Migration 0029 stores each compiler-authored `compilation_basis` separately on its
Report section. The ordinary section body still contains the complete exported
text. Reading uses the separately stored basis to display prose and provenance.
The edit form submits prose only; submitted text is never stripped by matching a
suffix, even when the reviewer intentionally copies the exact stored basis.
User/source text containing the same heading stays visible and editable. Existing sections
receive an empty basis field, preserving their body verbatim instead of guessing
where provenance starts. Startup adds the column idempotently under a database
write transaction. Synthetic backup/clean-restore and legacy-column upgrade tests
verify retained prose and provenance.

A deleted compiled Report leaves its successful request available for explicit
retry. Retrying that request creates one new draft from current selected work;
it does not resurrect or silently restore the deleted document. Unavailable
source-check documents, including uncited human overrides, fail validation even
when their version and stored text have not changed.

Generated provenance has bounded attribution text and explicit omitted-attribution
counts, so many records supporting one passage cannot create an unsavable section.
Partial entity-category work retains attributed saved findings and reports the
unchecked categories rather than claiming that every source was analyzed.

Heartbeat renewal uses an independent SQLite connection while guarded source
validation is in progress. Lease-token, expiry, authorization and cancellation
checks remain transactional; a stale worker cannot renew its lease.

Successful report creation and its completion audit event share one transaction.
The content-free event retains the initiating actor, job identifier and new Report
identifier even after the Report is deleted. Failed worker outcomes, explicit
cancellation and retry are also recorded. Read-only administrator overrides do
not advertise report creation or editing. Matter purge deletes terminal
compilation requests in the same cleanup transaction as the remaining work.

Section editors reserve capacity for immutable review-basis text and display the
remaining prose limit. Matter closure and backup both wait for queued or running
report compilation; closure displays those jobs before offering deletion.

The synthetic speaker-review acceptance test now accepts either transient refresh
state and checks the eventual persisted summary against the current speaker basis.
Its frozen node/file digests and aggregate fingerprint are refreshed explicitly;
case selection, synthetic fixtures, and all other node digests are unchanged.
Offline focused compilation counts selected saved works before expanding their
findings and labels included text as unfiltered with relevance not checked.
