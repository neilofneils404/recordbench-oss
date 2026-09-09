# Contributor starting points

For scoped product work, start with the [portable product slices](product-slices/README.md).
They record code-backed findings, dependencies, implementation boundaries, and
synthetic acceptance criteria for installation, onboarding, accounts/groups,
exact search, deep review, Reports, and People/Places/Things. The briefs are
proposals; refresh upstream and coordinate an individual slice before coding.

These are candidate contributions, not assignments. Open a short issue with a
synthetic reproduction or proposed acceptance path; check existing PRs before
starting. Maintainers coordinate ownership and break larger work into small
reviewable changes. No access to a private deployment is needed.

| Area | Useful first contribution | Acceptance direction |
| --- | --- | --- |
| Browser CI | Run existing loose-file and Report-bundle journeys on hosted runners | Synthetic-only; assertion failures fail CI; bounded startup and cleanup |
| Database CI | Run the existing PostgreSQL/pgvector tests in an isolated service | Tests execute rather than skip; citation and matter-isolation checks pass |
| Accessibility | Audit one Sources or Reports workflow for keyboard use and reflow | Reproducible before/after browser evidence; no global redesign |
| Installation docs | Try the CPU evaluation profile from the public playbook | Record generic prerequisites, confusing steps, and recovery without real logs |
| Source organization | Show identical-content groups without merging source records | Matter-local; distinct paths/production occurrences and citations preserved |
| Intake coverage | Account for skipped files and unprocessed email attachments | Every selected item has an honest state; no implied attachment search |

Current capabilities and limits are in the README. Authentication, retention,
deletion, import/export formats, shared editing, model changes, and migrations
need an agreed contract before implementation. Durable matters and reopenable
packages remain design proposals, not supported features.
