# Trusted matter continuity A — connect existing Case notes

Status: locally implemented; final acceptance and landing pending. Not Done.
Reference: `622cf7a03b67c6d850f06799c98b2333b2efd52d`.
The [cruise](../EXIT_ALPHA_CRUISE.md) is the binding queue.

## User outcome and scope

An authorized reviewer returns to Case notes and sees existing notes alongside
saved identities and events/assertions, with links to existing record editing,
chronology, Review map, Reports and original sources. Two authorized reviewers
see the same matter records; note labels remain separate from stable identities.
Human confirmation does not establish independent truth. A disputed status,
competing source account and Review map comparison candidate retain their
different meanings. There is no inferred dispute category.

The page works without generation. Opening it adds no model calls, knowledge
mutations, selections, jobs or stored projections. Existing operational access
auditing and recent-activity tracking continue. Note editing, pinning, confirmed
or explicitly selected note reuse and exports keep their existing contracts.
Export case notes still exports notes, not a new combined knowledge artifact.

## Read contract

- Eight identities per page ordered by name and stable ID; six events/assertions
  ordered by explicit ordering date, then undated records, creation time and ID.
  The two page controls are independent of note filtering/pagination. All entity
  and assertion review statuses, including dismissed, are included and labeled.
- At most two mentions per identity and two accounts **per stance** per record.
  Counts and omitted records/references remain visible with complete-record links.
  Up to three aliases appear; additional aliases are explicitly counted.
  Statements/excerpts have labeled complete-record routes and visible ellipses.
  An out-of-range page displays the latest available page with its actual number.
- Review status and original-reference availability are independent. Unavailable
  support keeps attribution and historical text but has no live original link.
  Sources are validated by their exact saved metadata, never by token alone.
- Projection SQL shares the existing authorized SQLite transaction and source
  guard, batches admitted references, loads no correction histories and performs
  no writes. The HTTP response rechecks access after rendering and is uncached.
  Existing administrator read-only Case notes access remains read-only.
- Source links preserve the matter-local notebook filters and knowledge pages as
  return context, including through the full source reader. Existing source
  routes revalidate support. A later reload reads current human revisions.

No schema, graph database, automatic summary, identity/relationship inference,
new notebook, background-source workflow, selection persistence or retention/
reopen behavior is added. Increments B/C and model qualification are separate.

## Acceptance

Use synthetic notes, two same-name identities, an alias, an allegation, a competing
account later than supporting accounts, an uncertain date and unavailable support.
Prove two-reviewer inspection/edit/reload, independent paging and honest omissions,
no knowledge writes on GET, generation unavailable, escaped source instructions,
cross-matter denial and access revocation during response rendering. Exercise
source-return links, existing exports and note reuse, keyboard navigation,
390-pixel reflow, both themes and a reopened runtime. Source text cannot authorize
actions or change scope. Existing finite fixtures establish only their tested cases.

Record commands actually executed and limitations in this brief before handoff.
Do not mark Done before acceptance and landing. Preserve all unrelated holds.

## Local validation — September 21, 2026

The clean implementation branch starts at the reference revision above; no
upstream difference from the reviewed handoff baseline was found. Existing
onboarding edits in another checkout were preserved. No schema or persistent
record shape changed, so this increment introduces no migration/restore step.

Executed with Python 3.12 and synthetic fixtures:

- Focused projection, notebook, conflict, graph and source-navigation selection:
  **74 passed**, including **22** new continuity service/workflow cases.
- Browser runner failure/receipt contracts: **88 passed**, including failure of
  the newly registered continuity journey. CI uses the existing runner and its
  bounded artifact allowlist; there is no separate browser harness or CI job.
- PostgreSQL integration: **7 passed, zero skipped**, with the learned-model
  evaluation explicitly deselected. A disposable instance used the existing
  pinned pgvector image; it was removed after the checks.
- Bundled transcription suite: **194 passed**. Standard, Kerberos and dedicated
  local-account Compose graph checks passed. Compilation and diff whitespace
  checks passed.
- Standalone browser acceptance passed with Chrome 134: reopened runtime,
  unavailable generator, same-name identities, alias, historical source state,
  keyboard navigation, both source stances, full-reader return, note filters,
  pagination/reload, Light/Dusk and 390-pixel reflow.
- Pinned browser runner: **all eight journeys passed** with Chrome
  **153.0.8010.36**, using checksum-verified cached archives. The seven existing
  journeys retained their acceptance and the new continuity journey passed all
  seven checks. An initial integration run passed the existing journeys but the
  new script rejected the runner's precreated empty output directory; after
  correcting that contract, the complete runner passed. Existing results still
  cannot be overwritten by a direct rerun into a nonempty output directory.
- Full application suite: **3,192 passed, nine skipped, one failed** in 760.63s.
  The failure was the existing
  `test_same_size_edit_with_restored_mtime_reloads_cached_snapshot`: its two
  writes received the same filesystem ctime. It reproduced on the fifth
  diagnostic attempt against an unmodified archive of the upstream reference.
  The whole local-account lifecycle module separately reran with **57 passed**.
  This is baseline flakiness, not a passing full-suite result. The final extra
  continuity and browser-runner cases are covered by the focused runs above.

Representative commands (use the existing contributor Python environment):

```console
umask 022
CASE_INTELLIGENCE_STORAGE_RESERVE_GIB=0 python -m pytest -q tests/test_matter_knowledge.py tests/test_matter_knowledge_workflow.py tests/test_matter_notebook.py tests/test_notebook_conflicts.py tests/test_evidence_graph.py tests/test_evidence_graph_workflow.py tests/test_assertion_navigation.py
python -m pytest -q tests/test_browser_acceptance_runner.py
python scripts/browser-accept-matter-knowledge.py --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver --output /tmp/generated-continuity-acceptance
python scripts/run-browser-acceptance.py --archives /path/to/verified-browser-archives --output /tmp/generated-browser-suite
python scripts/publication-check.py --skip-history
```

The generic working-tree sanitizer passed. The installed publication guard
reported identical pre-existing findings on the candidate and unmodified
upstream trees; the installed outgoing-history check of that upstream base also
blocked. Added content, including new files, passed the installed scanner.
These comparisons are diagnostic, not a waiver or publication clearance. The
repository-wide history scan also includes unrelated local refs; it is separate
from the exact outgoing-history check. No guard settings were changed.

The first complete-suite attempt was interrupted after account-directory tests
rejected group-writable fixtures created with the shell's `0002` umask. The
subsequent attempt uses `022`; no product permission check was weakened.
Synthetic acceptance is not confidential-casework readiness, model qualification,
an installed-node acceptance or a supported release. No push, merge, publication,
product installation or deployment was performed.

Next acceptance step: review the bounded diff, reconcile the baseline timing
test and existing publication findings without weakening their checks, then
obtain final Quality and maintainer landing acceptance after publication is
explicitly authorized. Continuity A stays pending until then; B/C are not selected.
