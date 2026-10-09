# Quality checks for documentation changes

Plain documentation changes do not start the application, PostgreSQL,
transcription, deployment-contract or browser suites. They still run exact-head
publication inspection of the complete outgoing history, independent secret
scanning, and the existing native review policy. The required `application`
check runs lightweight documentation and scope contract tests using only pytest,
then records that the full application suite is not applicable. This preserves
required-file, release-boundary, security-text and backup/restore documentation
checks without installing the application or browser dependencies. Scope
classification and publication inspection must also succeed. The other suite jobs report explicitly skipped;
this is not a claim that their tests ran. Required check names and branch
protections remain unchanged.

The fast path allows regular, non-executable Markdown files under `docs/` and
these root documents: `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`THIRD_PARTY_NOTICES.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md`. Added, edited,
deleted and renamed documentation qualifies when both sides of the change are
within that allowance. Assets, symlinks, executable files, agent instructions,
fixtures, unknown paths and mixed changes run the full gates. In particular,
Markdown fixtures inside source or test directories are not documentation.

Pull requests compare the complete head against its merge base with the target.
Feature-branch pushes inspect both the pushed change and the whole branch against
the default branch, so a documentation follow-up cannot conceal an earlier code
change. New feature branches use that same merge base. Default-branch pushes
compare the previous and new revision. Tags, force pushes, empty changes,
unavailable history and unrecognized metadata conservatively run the full gates.
Git's complete NUL-delimited diff is used, without rename heuristics or a
paginated API file list. An oversized diff also takes the full path.

The workflow is not filtered out by file paths: it always publishes the check
results needed by branch protection. If classification fails as a job, the
required application check fails; a missing output does not qualify for the
fast path. Publication failure also fails that required check. No manual label,
commit-message bypass, administrator exception or approval waiver is introduced.

Changes to the classifier or workflow itself require all existing suites.
Synthetic regression tests cover the path and mode boundary, complete branch
comparisons, code-to-documentation renames, missing history and failure handling.
No product behavior, deployment behavior or model configuration changes.

Initial local verification: **171 tests passed in 9.71 seconds** across scope
classification, publication candidate/history inspection, publication rules,
PostgreSQL report validation and browser-runner failure contracts. Actionlint
**1.7.7** (checksum-verified upstream archive) accepted the workflow. The generic
working-tree publication scan passed. PR #105 is the implementation review; its
full Quality runs and the documentation-only follow-up provide the hosted
execution record.

Hosted review identified an obsolete publication-job contract assertion and the
need to retain documentation contracts on the fast path. Both were corrected.
The expanded targeted set passed **177 tests in 9.34 seconds**. A fresh virtual
environment containing only pytest passed the fast-path **32 tests in 1.10
seconds**; a synthetic missing-README experiment was correctly rejected.
Actionlint and the generic publication scan passed again. The superseded hosted
runs were cancelled once the failing contract was identified; they are not
claimed as passes. Fresh full Quality and hosted review outcomes are recorded on PR #105.

## Source size ratchet

`tests/test_source_size_ratchet.py` checks Python modules under `src/` as part
of `make check`. Modules at or below 1,500 lines can grow or shrink freely and
need no entry in `tests/snapshots/source_line_counts.json`. The baseline records
only existing oversized modules: they may shrink without editing it, but may
not grow beyond their recorded count. Lowering a baseline after a reduction is
optional; never raise it to admit growth. A module crossing 1,500 lines must be
split into smaller modules. Remove baseline entries when their files are deleted.
Counts include comments, blank lines and a final line without a newline.

## Verify a documentation-only run

For a qualifying same-repository PR, inspect both the branch-push and pull-request
runs. For a PR from a contributor's fork, the upstream pull-request run is the
authoritative evidence: no upstream branch-push run is expected, and the fork
does not need Actions enabled. In the applicable runs, verify:

- `change-scope` reports plain documentation only.
- `publication-scan` and `secret-scan` both pass.
- `application` passes its dependency checks and the lightweight documentation
  and scope tests. It records that the full application suite is not applicable.
  Application bootstrap, system/media dependency setup, compilation and the
  full-suite test step are skipped.
- `postgres-integration`, `transcription`, `deployment-contract` and
  `synthetic-browser` are skipped without starting their runners or services.
- The native review-policy status and approval still apply before merge.

After landing, the default-branch push should produce the same outcome. A skipped
suite is expected only when the scope check proved the documentation allowance;
it must never be reported as an executed test pass. Record run IDs and observed
outcomes in the PR rather than creating another receipt commit solely to record
the preceding receipt's checks.

## Diagnose incomplete application runs

The full application suite prints each test node and its outcome as it runs,
with unbuffered output. A failure is identifiable even if a later test stalls
and the job reaches its timeout. Short tracebacks, failure/skip summaries and
the 25 slowest test phases are printed when pytest finishes. This does not stop
at the first failure, retry failing tests, change selection or extend timeouts.
Captured stdout, stderr and logs are excluded from failure output and JUnit
logging; fixtures and assertion messages must still be synthetic.

The job attempts to retain only `application-results.xml` for five days, on
success or failure, with the run ID and attempt in the artifact name. JUnit XML
is finalized at session end: a hard cancellation can prevent both report
creation and artifact upload. Use the streamed job log for an incomplete run;
missing XML is not evidence of success. No workspace, database, media, secret
scanner output or environment dump is uploaded by this step.

### Duplicate push and PR runs

Branch pushes and PR merge candidates still run independently. Deduplication
is deferred: an open PR alone does not prove that its current merge-candidate
workflow will run. In particular, [GitHub does not run `pull_request` workflows
on merge conflicts](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).
A shared concurrency key can cancel the required integration run, while simply
skipping a same-named required job can produce an ambiguous green result.
Read-only `contents` permission also does not establish PR/API access.

A follow-up must prove exact-head and base coverage, missing/failed API lookup
fallback, fork/conflict and event-race behavior, and native required-check
eligibility before suppressing work. Default-branch and tag pushes, branches
without a PR, exact-head publication inspection and secret scanning must retain
their existing coverage. Until then, inspect both runs and do not describe a
cancelled or skipped application run as a test pass. Required names, triggers,
permissions, concurrency and the conservative scope policy are unchanged.
