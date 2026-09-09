# Browser account management

An administrator opens **People** from the account menu to create a local
account, change its display name or password, disable/re-enable sign-in, or
change its application role. The first local administrator is directed there
after signing in. The setup checklist explains the next steps: create a
teammate, have them sign in once, create a matter, add them from **Case team**,
and verify their access. Application roles and matter membership are separate.

Passwords are entered twice and are never redisplayed. Password, state and role
changes end existing sessions at their next request. Removing your own access
requires explicit confirmation and signs you out. The final enabled
administrator cannot be removed. A stale form displays current account data
and asks you to review before retrying.

## New installation

For local accounts, explicitly enable the narrow writable account profile:

```bash
./install --auth local --enable-account-management
```

The installer creates one canonical `accounts/local-accounts.json`, mode `0600`,
inside an owner-only `0700` directory. `compose.local-accounts.yaml` mounts that
directory at `/var/lib/recordbench-accounts` in the app and operator account tool.
The original secrets mount remains read-only in the app. No duplicate account
database or writable session-key, provider-secret or database-credential mount
is introduced. Installer resume and updates retain this profile in
`installation.json`. The flag is only accepted for a new explicit local install.

The profile requires a local POSIX filesystem with reliable locks, atomic rename
and durable file/directory sync. The account directory may contain only the
canonical account file, its lock file and writer temporary files. Startup and
each browser write check that boundary. Do not put backups or other secrets
there. Without this profile, People explains that an operator must enable it
and links to setup instructions. OIDC and Kerberos installations direct account
changes to the configured identity provider and retain matter-team controls.

## Existing node: explicit stopped-node relocation

Use the service-account identity and the matching reviewed release. All paths
below are generic examples; choose the node's actual paths in the operator
environment. Do not perform this through an HTTP request.

1. Stop the application and every operator account writer. Back up configuration,
   `installation.json`, the account file, control database and session-key
   boundary following [Storage and backup](STORAGE_AND_BACKUP.md).
2. If accounts are version 1, run the separate verified migration in
   [Local account lifecycle](LOCAL_ACCOUNT_LIFECYCLE.md) first.
3. Relocate the same version 2 account file with a new recovery destination:

   ```bash
   recordbench accounts relocate \
     --file /srv/recordbench/secrets/local-accounts.json \
     --destination /srv/recordbench/accounts/local-accounts.json \
     --backup-file /mnt/recovery/recordbench/accounts-before-browser.json \
     --confirm-stopped
   ```

   Run on the host in the reviewed operator environment, or explicitly mount
   these directories into the account tool. The destination directory must be
   empty and `0700`. The command saves and verifies an exact `0600` recovery
   copy, writes and syncs the new file, rotates account session revisions, then
   removes and syncs the old canonical file. If interrupted after writing the
   destination, keep writers stopped and inspect both paths before resuming.
4. Set `RECORDBENCH_LOCAL_ACCOUNT_ROOT=/srv/recordbench/accounts` in `compose.env`.
   Set `CASE_INTELLIGENCE_LOCAL_ACCOUNTS_FILE=/var/lib/recordbench-accounts/local-accounts.json`
   and `CASE_INTELLIGENCE_LOCAL_ACCOUNT_MANAGEMENT_ROOT=/var/lib/recordbench-accounts`
   in `config/recordbench.env`. Set `local_account_management` to `true` in
   `installation.json`. Preserve the other configuration fields and owner-only
   permissions. Include `compose.local-accounts.yaml` after `compose.yaml` for
   direct Compose operations; installer operations load it from node metadata.
5. Validate the rendered Compose graph, restart the application, and sign in
   again. Confirm the app's original secrets mount remains read-only. With
   synthetic accounts, create two reviewers, add only one to a synthetic matter,
   confirm only that reviewer can open it, then reset and disable that account
   and confirm its existing sessions lose access.

## Backup, clean restore and rollback

Include the dedicated account directory in the stopped-writer backup boundary.
Restore its canonical file to a new owner-controlled `0700` directory with mode
`0600`, enable the matching profile and configuration, and verify synthetic
administrator sign-in, account mutation and matter authorization. A synthetic
clean restore regression checks that the verified relocation recovery copy is
readable and authenticates the same account; an installed-node recovery drill
remains an operator acceptance requirement.

To roll back the layout, stop all writers and the application. Retain a protected
copy of the latest canonical accounts, restore the pre-relocation recovery file
at the old secrets path with owner-only permissions, remove the management-root
setting and overlay, set `local_account_management` to `false`, and restore the
previous account-file setting. Restart the compatible release and verify access.
Changes after the recovery copy are absent and must be reconciled deliberately.
Never run writers against both locations or copy lock files into a live node.

## Authorization and audit

Browser routes require authenticated administrator access and a valid CSRF
token. Before saving, the shared repository rechecks the actor's current local
session and administrator role under its process writer lock, then compares a
keyed edit token with current account data. Last-administrator protection shares
that lock. Forms have a bounded body size, and concurrent password work is
limited. HTTP requests cannot supply a filesystem path, migrate accounts or
initialize an administrator.

Content-minimized audit events record the authenticated actor, action and an
opaque target identifier. A requested event must persist before account
replacement; completion is recorded afterward. A completion-audit failure is
reported without pretending the account change was rolled back. Storage errors
require a fresh read before retrying. Neither event includes passwords, hashes,
session revisions or submitted form bodies.
