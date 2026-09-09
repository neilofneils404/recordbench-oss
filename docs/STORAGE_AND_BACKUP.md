# Storage, backup, and recovery

Matter storage must be a dedicated absolute directory initialized with a
RecordBench ownership marker. The application will not delete outside that
boundary. A local filesystem or host-mounted NAS path is supported; the
installer does not mount network shares or store NAS credentials.

Capacity policy separately limits a matter, an upload collection, media files,
documents, and the protected free-space reserve. Thousands of sources are
represented through paginated catalogs, background jobs, readiness counts, and
partial-query behavior. One failed source is excluded and reported; it does not
make every other indexed source unusable.

## Choose your backup method

Operators can use their existing backup system or the optional bundled restic
tool. Installing RecordBench does not enroll the host in a backup service.
The bundled tool takes an operator-selected absolute destination on a filesystem
available to the host, including storage mounted by the operating system.
RecordBench does not mount shares, collect storage credentials, or require a
particular storage vendor. Configure encryption, access, retention and recovery
for the chosen method and test it before depending on it.

Whichever method you choose, capture these as one consistent boundary:

- managed matter storage;
- the control SQLite database and session key;
- generated configuration and secrets;
- the dedicated canonical account directory when browser account management is enabled;
- the PostgreSQL projection dump (or a separately tested projection rebuild);
- version/install metadata and integrity hashes.

The transient transcription queue, model cache, container images, and other
rebuildable caches are excluded. Keep the matching reviewed release distribution
available too; the bundled snapshot records installation/version metadata,
not a copy of every release capsule or container image.

An external backup system must stop application writers or provide an
equivalent tested consistent snapshot across the control database, managed
registries/storage and projection. A file copy of a running SQLite database
is insufficient, especially when its journal/WAL is separate. Test recovery in
an isolated target, including registry integrity and matching source versions.
For updates using a verified external backup, `./install update --no-backup`
skips the bundled pre-update backup requirement; it does not verify that
external backup. This flag does not bypass a configured bundled backup's
failed or deferred result.

## Optional bundled backup

The bundled method uses encrypted restic storage with the recovery password
copied to a separate protected location. The repository and recovery credential
must not live inside the node or inside each other. Scheduling is opt-in.

Initialize and run a backup with:

```bash
./install backup --root /srv/recordbench \
  --repository /mnt/backup/recordbench/restic \
  --recovery-key-output /mnt/recovery/recordbench-restic-password \
  --schedule-backups
```

The backup checks every durable queue. If work is active, it records a deferred
state and the quiet-hour timer retries. Otherwise it stops the app and gateway,
then dumps PostgreSQL and creates hard-link snapshots beside the node state and
managed matter storage—even when those roots are on different filesystems—and
restarts service before encrypted transfer. Every SQLite store in both snapshot
trees is copied with its journal companions, consolidated through SQLite's
backup API, checked, and detached before restart. Live database or WAL writes
after restart therefore cannot change the frozen copy. Symbolic links and
unsupported file types in either snapshot tree cause a failed backup.

The PostgreSQL dump belongs to the same stopped application boundary as the
source/control stores. The app remains stopped during the dump and SQLite
consolidation; allow for that time in the maintenance window. Failure during
capture attempts to restart the app and gateway and removes temporary snapshot
trees. The tool retains its normal locking, active-job deferral, encryption and
retention behavior.

The tool verifies all SQLite stores, control hashes and the PostgreSQL dump
listing. Its routine repository check reads the fixed `1/14` subset; it does
not rotate automatically. Use `restic check --read-data` with your configured
repository/credential for a full data read when required by your verification
policy.

Check status and perform the actual recovery test:

```bash
./install backup --root /srv/recordbench
./install restore --root /srv/recordbench \
  --restore-target /srv/recordbench-restore-drill-001
```

Restore refuses an existing target and never connects drill data to the live
node. It asks restic to verify restored files, checks both snapshot trees,
requires the managed-storage marker, and validates every control and managed
SQLite store. New snapshots record SQLite inventory counts and restore checks
those counts; older snapshots without counts still receive all-store checks.
The receipt reports total and managed SQLite stores separately. The routine
drill lists the PostgreSQL dump; an actual import into a disposable database is
an additional recovery acceptance step. Inspect the receipt, then remove the
exact drill directory yourself; it contains decrypted confidential state.
Never declare backup ready from a successful upload alone.

## Synthetic consistency verification

The regression suite simulates writes completing at stop and new writes after
restart. It checks DELETE-journal registries, WAL control databases, matching
projection capture, failed/corrupt/missing stores, symlink refusal, cleanup and
unchanged active-work deferral. To additionally exercise a real encrypted
repository and a real PostgreSQL dump/import using only synthetic state:

```bash
# Requires restic, Docker and an already installed pgvector/pgvector:pg17 image.
RECORDBENCH_BACKUP_INTEGRATION=1 python -m pytest tests/test_backup_consistency.py -q
```

This opt-in test uses an image already on the host, a disposable database with
no network, no published port or live volume, and a temporary repository. It
checks a full repository data read, restored SQLite values, PostgreSQL import
and `pg_amcheck`. The database container is removed even on failure. Test files
are synthetic pytest temporary data. It simulates app stop/start; it does not
replace an operator's installed-node or replacement-host acceptance.

The tooling remains prerelease. Do not depend on this candidate as the sole copy
of retained work product until your own scheduled backup and restore drill pass.

## Browser account snapshot validation

When the dedicated browser-account profile is enabled, backup requires its
canonical `local-accounts.json` in the frozen copy before application restart,
transfer or retention. The copied directory must be owner-only `0700` and its
account/lock/temp files regular owner-only `0600` files. The canonical file is
bounded to 1 MiB and must contain a valid version 2 store with an enabled
administrator. Missing files, malformed JSON, invalid account fields, unusable
Argon2id encodings or permissions fail the snapshot; the application restart
recovery still runs. Restore repeats this check against the restored installation
record as well as checking file hashes, so checksums alone do not establish a
usable account format.

Runtime and backup share a standard-library format validator for account shape,
PHC Argon2id encoding, parameter ranges and revision fields. The backup tool runs
this exact bundled validator in isolated Python, without relying on host Argon2
packages or ambient Python imports. Runtime readers retain their additional
argon2-cffi parameter validation and password authentication. Structural backup
validation cannot establish that an operator knows a working administrator
password; the clean restore drill must still verify synthetic sign-in and
administrator recovery. The suite covers a clean account restore, corrupted
frozen copies, invalid modes, missing administrators and malformed hashes.
