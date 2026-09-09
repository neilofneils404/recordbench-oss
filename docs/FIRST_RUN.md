# Installation handoff and team setup

The installer ends with the configured HTTPS sign-in URL, authentication mode,
initial local administrator username when recorded, observed preparation and
runtime states, and the next incomplete step. It never treats a prepared node
as a successful browser sign-in. Passwords and tokens are not included in phase
receipts or the handoff.

## Continue an interrupted installation

Run `./install install --root /srv/recordbench --resume` using the same reviewed
release and service-account identity. Paths with spaces are quoted in the
printed command. Resume uses the saved configuration, account-directory profile,
initial administrator identity, model selection and storage boundary. Before any
Compose command, it rechecks the entered node path, all protected storage ancestors and saved mount coordinates, then restores the saved
authentication, TLS, model and GPU choices for preflight. Conflicting saved
coordinates or unsafe replacements stop without launching or stopping services.
It checks the Compose graph, validates existing storage and accounts through the
operator tools, and reuses existing accounts and secrets. It does not reset sources or
reinitialize an existing account file. A relocated canonical account directory
is read from the saved Compose mount and must pass the same protected-ancestry
checks; it does not need to move back under the node root.

For an interruption before initial administrator creation, provide the password
again through the existing protected terminal or stdin option. The password
is deliberately not saved for resume. Older nodes without recorded initial
administrator metadata still require explicit `--admin-username` and
`--admin-display-name` if account creation was never completed. An existing
valid account file does not require those bootstrap inputs.

Model staging writes a version 2 receipt binding the catalog digest, exact
selected groups, review profile, snapshot pathnames, file sizes and artifact
hashes. Each file symlink also retains its literal target and resolved blob path;
removing, repointing or replacing a snapshot link invalidates verification even
when the original blob still exists. Directory symlinks and artifacts outside the
approved cache are refused. Before resumed staging, `stage-models.py verify` checks that receipt and all recorded bytes
offline, without writing files or accepting a token. A matching selection skips
staging and gated-token entry. Missing, changed or older version 1/unreceipted
selections run the normal pinned staging path. The model catalog, revisions and licenses
are unchanged by this feature. Hash verification establishes retained artifact
integrity; it does not replace runtime loading or representative evaluation.

Before resumed runtime checks, the current launcher's stdlib verifier checks the
cache offline against the installed release's exact catalog. An unattended
resume that needs gated diarization staging must select `--accept-model-terms`
and `--hf-token-stdin` before any Compose command or phase write. A verified
cached selection requires neither flag nor token entry. Container-side
verification still repeats before the retained cache is reused during provisioning.
Updates perform the saved-coordinate and ancestry checks before their backup or
Compose work; this feature does not change model revisions during an update.

## Read the states correctly

The owner-only `state/install-progress.json` receipt has `format_version: 1`,
the installed release identifier, fixed phase names/states and observation time.
It contains no passwords, tokens, source text or user identity. States are
`checking`, `complete`, `incomplete`, or `not-selected`.

| State | What was observed |
| --- | --- |
| Prepared | Runtime build and storage/account/model preparation finished. |
| Running | The application answered its health probe. |
| Login reachable | The bounded loopback sign-in endpoint answered; Kerberos also issued the expected protected gateway challenge. |
| Basic review | Health reported source review, storage and required malware scanning ready. |
| Selected capabilities | The health contract reported every selected optional capability ready. |
| Browser sign-in | Always left for a person to verify in the actual browser. |

Resume revalidates completed preparation; its old receipt is not a readiness
override. `--prepare-only` performs preparation without starting services. A
failed selected model remains incomplete while healthy basic review can still
be reported separately. `./install doctor --root /srv/recordbench` repeats the
live checks and prints the handoff. A failure retains node state and reports the
next unverified phase for recovery.

The local loopback probe does not validate the certificate trust store on the
operator's browser or a teammate's device. A generated smoke certificate remains
for isolated loopback testing. Arrange the matching hostname and trusted TLS
through the operator before team access; do not bypass browser protection.

Receipts are derived and are not a new account or source store. Existing nodes
without them are revalidated on resume. Unknown receipt formats fail closed and
require the matching installer. Normal configuration/control backups retain the
installation coordinates; a restore may reconstruct phase observations through
resume/doctor. The model-cache receipt is rebuildable with that cache. No database
migration or optimistic checklist completion field is introduced.

## First administrator in the browser

An administrator without an assigned matter opens **Team setup** after default
sign-in. Explicit destinations are retained. The same page remains in the
account menu and workspace health page for later visits.

1. Check actual basic and optional capability status.
2. Give a synthetic teammate a sign-in through **People** or the configured
   identity provider, then have them sign in once.
3. Create a synthetic practice matter or choose an existing matter whose case
   team you have joined.
4. Add synthetic sources through **Sources**, wait for preparation, and resolve
   reported failures. Counts come from the existing readiness projection.
5. Add the teammate from **Case team**. Admission, application administrator
   roles and matter membership remain separate.
6. Have the teammate open that matter in their own session. The page reports
   whether a current eligible teammate has a successful matter-open audit event
   after their latest membership grant. A same-time observation is insufficient. Revoking/regranting access requires a
   fresh opened page. Separately confirm that an unassigned synthetic account
   is denied and that the sources are usable.

Local, OIDC and Kerberos modes show their own identity guidance. Setup is an
authenticated administrator-only read path; it cannot create an initial
administrator or claim an installation. Progress survives restart because it
is derived from existing readiness, current memberships and audit evidence.
It is not a certification of source accuracy, model quality or negative access.

## Acceptance before adoption

Run the portable synthetic browser runner described in
[Browser account management](LOCAL_ACCOUNT_BROWSER.md). It now also checks the
setup entry point, narrow layout and recorded teammate-open evidence. Run the
installer interruption, account and onboarding regressions on the integration
checkout. Before adopting that revision, independently complete clean Linux
installation plus interrupted resume, actual source preparation, selected-model
runtime checks, two-user access, and an installed-node backup/clean-restore drill
with synthetic data on the intended host. A green PR or loopback browser check
does not establish those target-host outcomes.

A resumed dry-run can use the verified local model receipt to plan an offline
restart without requesting a staging token. Real provisioning still verifies the
selected model artifacts through its runtime image before launch.
