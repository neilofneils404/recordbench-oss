# RecordBench contributor guide

This repository is the environment-neutral open-source distribution. Never add
real case material, internal hostnames, private addresses, staff identities,
credentials, keytabs, certificates, database files, runtime state, or private
deployment overlays.

Treat this repository and every GitHub interaction as public. Before any push,
run the installed pre-push publication check; never bypass it. Before posting
PR text, comments, attachments, or release assets, separately inspect their
content and metadata for private information. Hosted CI runs after upload and
cannot prevent the initial disclosure. Private deployment facts belong outside
this repository, including in plans and agent handoffs. Read docs/PUBLIC_ALPHA.md.

Actual hosted Codex code review is mandatory on the final implemented PR head,
with reconciled findings and full-head maintainer acceptance under
`docs/PUBLIC_ALPHA.md`. Local review, labels and quota messages cannot replace
it. Hosted security review is optional; security-sensitive changes still need a
focused security assessment and disposition of real findings. Do not request
hosted reviews automatically on PR open or synchronize. Publication safeguards,
Quality gates, Gitleaks and native protections always apply.

Before changing deployment behavior, read `docs/ARCHITECTURE.md`,
`docs/SECURITY_MODEL.md`, and the relevant runbook. Keep services private by
default, preserve the trusted-proxy identity boundary, and run the publication
sanitizer plus unit tests before committing.

All fixtures must be synthetic. Model changes require an exact revision,
license record, local/offline readiness test, and representative evaluation.
Schema or storage changes require backup and clean restore evidence.

## Start and resume here

Start by reading **Current state** and **PR rules** in
[docs/EXIT_ALPHA_CRUISE.md](docs/EXIT_ALPHA_CRUISE.md) and the relevant linked
brief. Verify the actual checkout, branch and upstream PR state before acting.
Respect existing holds; when no product increment is selected, ask before
choosing a new one.

Update that existing **Current state** section with the normal authorized
commit/PR only when the goal, unresolved blocker or next useful action
materially changes. Keep it short, link evidence, distinguish proposed, local
and landed work, and preserve historical receipts. Do not add session logs,
duplicate Git/CI summaries, new tracking files or manual handoff requests.

This continuity practice preserves all existing publication, validation and
authorization safeguards; it grants no additional commit, push, merge or
deployment authorization.

## Upstream role

This repository is the authoritative source for portable RecordBench product
behavior. General application, workflow, accessibility, ingestion, retrieval,
media, export, installer, and operator improvements should be implemented and
validated here before a downstream deployment adopts them whenever practical.

A defect first observed in a private deployment must arrive here as a
content-free behavioral description and a synthetic reproduction. Do not
cherry-pick private deployment history, copy private logs or configuration, or
mention a private organization in a commit, issue, fixture, or pull request.
Implement the generalized correction in this clean tree and let downstreams
consume the reviewed OSS revision.

Keep deployment overlays outside this repository. Release tags are immutable;
follow-up corrections receive a new commit and release rather than a moved tag.
Every behavioral change needs a synthetic regression, applicable documentation,
and a clear statement of the user outcome and validation performed.
