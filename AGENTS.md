# RecordBench contributor guide

This repository is the environment-neutral open-source distribution. Never add
real case material, internal hostnames, private addresses, staff identities,
credentials, keytabs, certificates, database files, runtime state, or private
deployment overlays.

Before changing deployment behavior, read `docs/ARCHITECTURE.md`,
`docs/SECURITY_MODEL.md`, and the relevant runbook. Keep services private by
default, preserve the trusted-proxy identity boundary, and run the publication
sanitizer plus unit tests before committing.

All fixtures must be synthetic. Model changes require an exact revision,
license record, local/offline readiness test, and representative evaluation.
Schema or storage changes require backup and clean restore evidence.
