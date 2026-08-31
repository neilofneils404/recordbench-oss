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

Backups must include:

- managed matter storage;
- the control SQLite database and session key;
- generated configuration and secrets;
- an optional PostgreSQL projection dump;
- version/install metadata and integrity hashes.

The transient transcription queue, model cache, container images, and other
rebuildable caches are excluded. Use encrypted restic storage with the recovery
password copied to a separate protected location. The repository and recovery
credential must not live inside the node or inside each other.

Initialize and run a backup with:

```bash
./install backup --root /srv/recordbench \
  --repository /mnt/backup/recordbench/restic \
  --recovery-key-output /mnt/recovery/recordbench-restic-password \
  --schedule-backups
```

The backup checks every durable queue. If work is active, it records a deferred
state and the quiet-hour timer retries. Otherwise it dumps PostgreSQL, briefly
stops the app and gateway, creates hard-link snapshots beside the node state and
managed matter storage—even when those roots are on different filesystems—and
restarts service before encrypted transfer. It verifies all SQLite stores,
control hashes, the PostgreSQL dump listing, and a rotating restic data subset.

Check status and perform the actual recovery test:

```bash
./install backup --root /srv/recordbench
./install restore --root /srv/recordbench \
  --restore-target /srv/recordbench-restore-drill-001
```

Restore refuses an existing target and never connects drill data to the live
node. Inspect the receipt, then remove the drill directory yourself. Never declare backup ready
from a successful upload alone—the restore drill is the test.

The tooling remains prerelease. Do not depend on this candidate as the sole copy
of retained work product until your own scheduled backup and restore drill pass.
