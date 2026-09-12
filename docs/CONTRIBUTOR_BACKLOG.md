# Contributor starting points

Use the [product north star](PRODUCT_NORTH_STAR.md) to frame the user outcome.
The [assessment and delivery plan](PRODUCT_DIRECTION_2026-09-12.md) connects
individual slices to the complete case-team review experience.

For scoped product work, start with the [portable product slices](product-slices/README.md).
They record code-backed findings, dependencies, implementation boundaries, and
synthetic acceptance criteria for installation, onboarding, accounts/groups,
exact search, deep review, Reports, and People/Places/Things. Check each
brief's Status line and the [exit-alpha cruise](EXIT_ALPHA_CRUISE.md) before
coding; the cruise owns the active step. Refresh upstream and coordinate remaining work.

These are candidate contributions, not assignments. Open a short issue with a
synthetic reproduction or proposed acceptance path; check existing PRs before
starting. Maintainers coordinate ownership and break larger work into small
reviewable changes. No access to a private deployment is needed.

| Area | Useful first contribution | Acceptance direction |
| --- | --- | --- |
| Browser CI | Maintain the hosted synthetic intake and Report-bundle journeys; extend scoped coverage | Synthetic-only; assertion failures fail CI; bounded startup and cleanup |
| Database CI | Maintain the `postgres-integration` Quality gates job and extend synthetic coverage | Existing database tests must pass without skips; slices 00/08 exact-search PostgreSQL acceptance remains pending |
| Accessibility | Audit one Sources or Reports workflow for keyboard use and reflow | Reproducible before/after browser evidence; no global redesign |
| Installation docs | Try the CPU evaluation profile from the public playbook | Record generic prerequisites, confusing steps, and recovery without real logs |
| Source organization | Show identical-content groups without merging source records | Matter-local; distinct paths/production occurrences and citations preserved |
| Intake coverage | Account for skipped files and unprocessed email attachments | Every selected item has an honest state; no implied attachment search |

Current capabilities and limits are in the README. Authentication, retention,
deletion, import/export formats, shared editing, model changes, and migrations
need an agreed contract before implementation. Durable matters and reopenable
packages remain design proposals, not supported features.
