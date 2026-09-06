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

Do not merge until GitHub Codex code and security reviews complete on the final
commit, all findings are resolved or explicitly reconciled, and required CI
passes. A local or subagent review is additional evidence, not a substitute.

Before changing deployment behavior, read `docs/ARCHITECTURE.md`,
`docs/SECURITY_MODEL.md`, and the relevant runbook. Keep services private by
default, preserve the trusted-proxy identity boundary, and run the publication
sanitizer plus unit tests before committing.

All fixtures must be synthetic. Model changes require an exact revision,
license record, local/offline readiness test, and representative evaluation.
Schema or storage changes require backup and clean restore evidence.

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
