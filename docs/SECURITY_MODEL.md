# Security model

The experimental [Mac profile](MACOS.md) preserves Linux parser and storage
containment inside a local VM. Its native generation companion has a separate
macOS sandbox that denies non-loopback outbound connections; it must not be
treated as equivalent to a Linux network namespace without platform acceptance.

RecordBench assumes confidential case material and a trusted internal operator.
It does not assume uploaded files, browser headers, model output, or model hubs
are trustworthy.

Primary controls include authenticated server-side sessions, CSRF protection,
matter-scoped authorization at the data layer, trusted-proxy secrets, stream
malware scanning, bounded parsers/subprocesses, non-symlink storage rules,
private companion-service networks, offline model workers, immutable model
revisions, transcript/answer provenance, and content-free operational health.

The gateway is the only published service. Default binding is loopback. Local,
OIDC, and Kerberos modes require secure cookies and trusted TLS. Real secrets
are file-backed and excluded from Git. The installer never prints or retains a
Hugging Face token.

The publication gate scans both the working tree and available Git history for
private addresses, personal paths, credential material, secret-shaped literals,
and operator-supplied internal deny terms. It also inspects extracted PDF
metadata/text and members of Office/ZIP containers under fail-closed expansion
limits. A clean current tree is not sufficient if residue exists in an earlier
commit.

Models can be wrong, transcripts can mishear, diarization can miscluster, and
retrieval can omit relevant material. The UI must preserve citations,
limitations, coverage, excluded-source notices, and direct source review. Do
not represent a generated answer as an exhaustive review unless the dedicated
**Check every source** task actually evaluated each frozen source.

Matter closure is a separate, deliberate application policy: either the matter
owner or an authenticated RecordBench administrator may request permanent
deletion. Cross-owner administrator action is labelled explicitly and is
attributed to that administrator. The close workflow keeps a final export
available, refuses active work, requires exact-name and permanent-deletion
confirmation, preserves originals outside managed matter storage, removes the
complete workbench projection, and retains only content-minimized audit and
closure records.

Report vulnerabilities privately under [SECURITY.md](../SECURITY.md). Do not
attach case files, transcripts, credentials, or internal topology to a report.

## Matter naming

The [matter settings contract](MATTER_SETTINGS.md) permits owner/admin rename
under the existing authenticated authority. Ordinary members cannot rename.
The current-name comparison, active principal/matter and owner membership
checks, update, and content-free audit share an immediate control-database
transaction. Exact-name deletion confirmation serializes with that transaction.
No source identities, access grants, or external files change.

## Shared note mutations

[Case-note editing](CASE_NOTE_EDITING.md) rechecks active principal, membership,
matter and item identity with the displayed update token inside an immediate
transaction for edit, review and deletion. Tokens convey no access. Missing or
stale forms cannot overwrite, approve or delete newer text; recovery preserves
submitted edits only within the authorized matter. No note text is added to audit.

## Shared Report mutations

[Report editing](REPORT_EDITING.md) rechecks active principal, membership,
active matter and exact Report/section identity inside the same immediate
transaction as displayed-version/status checks and mutation. CSRF-protected
forms cannot bypass guards by omitting tokens. Recovery reauthorizes the matter
before showing saved work or a submitted draft; deleted work is not recreated.
Existing success audit contains operation metadata, without old/new Report text.

## Shared source validation

[Team source validation](REVIEW_VALIDATION.md) requires the displayed decision
revision and checks active principal, membership, matter and exact run/document
inside one immediate write transaction. Pending decisions cannot be adjudicated.
Recovery reauthorizes the matter before showing current or proposed human work;
deleted/unavailable reviews do not become new rows. Machine completion and
existing source-change invalidation serialize with human edits and advance the
same revision metadata. Success audit retains operation metadata without notes.

## Selection receipts

[Selected-file receipts](INTAKE_RECEIPTS.md) retain browser-reported inventory
and selection-level exclusions. They explicitly identify that origin in the UI,
API and downloads; they do not attest historical capacity or the contents of a
file chooser. Independent server filename checks, authoritative upload admission,
received-byte counts and exact source availability remain separate. Browser
review states never authorize upload. Receipt metadata has atomic cumulative
matter, creator and workspace limits. Only owners may discard receipts with no
received data, including cancelling bound empty upload attempts. The same source
mutation lock covers chunk writes/offset commits and cleanup; cleanup checks saved
partial files as well as control rows. Requests recheck upload state after reading
their body and acquiring that lock, so a delayed request cannot write after cleanup.
