# Fresh Linux alpha acceptance handoff

Use this handoff on a dedicated, disposable **Ubuntu 24.04 x86-64** host or VM
with systemd, an administrator login with sudo, and working internet access.
The planning target is 8 CPU cores, 16 GB RAM and 150 GB free SSD before source
data. These are advisory figures; leave the configured **100 GiB reserve** intact
and measure free space again after builds. This check covers the CPU `none`
profile with local browser account management. It requires no GPU, model token
or model download.

The maintainer must supply the full **candidate commit SHA separately**. This
document cannot name the commit that will eventually contain itself. Test that
exact candidate and report its SHA; a successful run of another revision does
not accept this candidate. Use only the bundled invented records and synthetic
accounts. Keep passwords, keys, node configuration and raw logs on the test host;
return the concise receipt below and the browser and installer JSON receipts.

## 1. Check out the candidate, then follow its guide

As the administrator, install Git if needed (`sudo apt-get update` followed by
`sudo apt-get install --yes git ca-certificates`). Run this block in your home
directory after replacing the placeholder. It intentionally stops if the SHA is
missing, malformed or unavailable:

```bash
set -e
candidate_sha='PASTE_THE_40_CHARACTER_CANDIDATE_SHA'
case "$candidate_sha" in *[!0-9a-f]*|'') exit 2 ;; esac
test "${#candidate_sha}" -eq 40 || exit 2
git clone --no-checkout https://github.com/neilofneils404/recordbench-oss.git recordbench-src
cd recordbench-src
git fetch --no-tags origin "$candidate_sha"
git checkout --detach "$candidate_sha"
test "$(git rev-parse HEAD)" = "$candidate_sha" || exit 2
test -z "$(git status --porcelain)" || exit 2
```

Read this candidate's [Try RecordBench guide](TRY_RECORDBENCH.md). Complete its
**Prepare the new host once** section, ending in the fresh `recordbench` service
account session. Repeat the checkout block above in that account's home, using
the same SHA. This creates the service account's own checkout; the administrator
copy is only for reading the instructions. Skip the guide's later `git clone`,
`cd` and `git rev-parse` lines because this checkout is already selected.

The browser check also needs host libraries. As the administrator, install the
Ubuntu browser dependencies used by this repository's browser CI, plus its
private-CA tool and the optional backup tool. The command uses Noble's actual
[ATK](https://packages.ubuntu.com/noble/libatk-bridge2.0-0t64) and
[GTK](https://packages.ubuntu.com/noble/libgtk-3-0t64) package names:

```bash
sudo apt-get install --yes --no-install-recommends \
  libnss3 libnss3-tools libatk-bridge2.0-0t64 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxrandr2 libgbm1 libasound2t64 libgtk-3-0t64 fonts-liberation restic
```

Run the browser as the unprivileged service account with its normal sandbox.
A host sandbox or missing-library failure is a failed prerequisite to diagnose;
do not add `--no-sandbox`, disable AppArmor or bypass certificate checks.
Ubuntu's user-namespace restriction can block the downloaded Chrome executable.
Use the [Chromium AppArmor guidance](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md)
to diagnose that restriction. If it blocks startup, mark automated browser
acceptance `blocked` and describe the bounded prerequisite; a policy change
requires separate operator review. The runner does not install an AppArmor
policy, and clean Ubuntu browser startup remains unverified until tested there.

Before installation, record CPU count, available RAM or VM/container memory
limit, free bytes on the Docker and node filesystems, Docker storage driver and
whether swap exists. Record cache state honestly:

| State | What the receipt must distinguish |
| --- | --- |
| Images and build cache | Empty engine, or preexisting/pulled images and cached layers. |
| Antivirus signatures | First FreshClam download from an empty signature volume, or an approved mirror/import/preseeded volume. |
| Browser archives | First pinned archive download, or previously downloaded archives. |

A new checkout on a warm engine is not a cold image build. Signed offline
antivirus import can validate recovery, but does not prove first-download access
or subsequent refresh. Do not delete unrelated Docker data to manufacture a cold
run. Use a new disposable VM when an empty engine is required.
If the default signature download is blocked, use the complete
[signed CVD acquisition and import recipe](ANTIVIRUS_RECOVERY.md#obtain-a-complete-signed-bundle-on-a-donor)
and record the import lane. Do not repeatedly retry an upstream cooldown.

## 2. Prepare, resume, and reach the first export

As `recordbench`, follow **Prepare and start the CPU node** in the candidate
guide: generate evaluation TLS, run preflight, supply the administrator password
through protected stdin, finish `--prepare-only`, then run `--resume` and
`doctor`. Keep its exact CPU/local-account/localhost choices. Preparation alone
does not start the browser. Record preparation, initial signature staging,
resume and first-ready durations separately, including any waiting or retries.

For a fully unattended run, create a random password in a new mode-0600 file
inside the service account's private home without printing it. Feed that file to
the guide's same `--password-stdin` command using input redirection instead of
its terminal prompt; pass it to the browser runner with `--admin-password-file`.
Do not put the password in a command argument, environment variable, receipt or
checkout. The installer only needs it again if account creation never completed.

Run the browser check **before manually creating any matter or extra account**:

```bash
python3 scripts/accept-installed-cpu.py \
  --url https://localhost:8443 \
  --node-root /srv/recordbench \
  --admin-username alpha-admin \
  --ca-file /var/lib/recordbench-home/evaluation-tls/ca.crt \
  --acknowledge-synthetic-evaluation
./install diagnostics --root /srv/recordbench
```

The runner privately prompts for the administrator password unless the protected
file option is supplied. It verifies TLS and the installed release before any
browser writes. Its source SHA and the node's installed release ID are separate
fields; retain both. See [Installed CPU browser acceptance](INSTALLED_CPU_ACCEPTANCE.md)
for its exact contract and JSON failure codes.
Compare the installed ID with the maintainer's ID calculated from a clean archive
of this candidate. Local test caches are excluded from the capsule fingerprint.
Its `phase_seconds` and `first_export_seconds` are measured from the runner's
own monotonic clock. The first-export value includes browser setup/download and
password waiting; separately record elapsed time before starting the runner to
report time from initial preparation to the first verified export.

The fixed positive journey is administrator sign-in, working styles and Activity,
two synthetic uploads, word and exact search, original-source review, a saved
case note, and a downloaded ZIP containing that note. The same run creates two
reviewers with matching display names and checks this three-account boundary:

| Session | Required result |
| --- | --- |
| Administrator | Select the non-first reviewer by its visible account label; confirmation and roster identify that account. |
| Selected reviewer | Matter and export return 200 after the grant; both return 404 in the same signed-in session after its last grant is removed. |
| Unassigned reviewer | Matter and export return 404 while the other reviewer has access. |

The runner starts the administrator first and uses at most two Chrome sessions
at once. Each new reviewer signs in once and closes to become eligible for the
case-team picker. The later access matrix uses fresh independent reviewer
sessions: unassigned denial first, then selected access and revocation without
signing that selected session in again.

Retain the runner's JSON output. A nonzero exit, failed phase or unrun phase is
not acceptance. Diagnose locally with [installation diagnostics](INSTALL_DIAGNOSTICS.md)
and [antivirus recovery](ANTIVIRUS_RECOVERY.md); record each manual intervention.
Do not weaken reserve, malware scanning, TLS, account checks or network isolation
to get a passing result. A mirror or offline import changes the signature lane
in the receipt and leaves cold default-download acceptance pending.

After a failed attempt, use `--allow-previous-synthetic-runs` only when the node
contains exclusively the runner's recognized synthetic accounts and matters.
Manually created accounts or matters do not qualify. For a new acceptance run
after manual experiments, use a fresh disposable node at the supplied candidate;
preserve the previous node and its private failure evidence. Do not remove
unknown work, disable accounts or loosen the empty-node check to force a rerun.
Running only a newer browser helper against an older installed capsule is a
useful diagnostic, but record both revisions and do not call it acceptance of
the newer full candidate.

Separately follow **Open it from your laptop** in the guide: verified SSH host,
loopback forward, matching public-CA fingerprint, dedicated Firefox evaluation
profile and explicit CA trust. Open the existing synthetic practice matter and
verify search, original review, saved note and export. Record this human browser
journey independently. A server-side runner cannot establish laptop SSH access
or Firefox trust setup; if no laptop/browser is available, mark that phase
`pending` rather than inferring it from the runner.

## 3. Restart without losing the practice work

Use the saved node's release and account overlay. As the service account:

```bash
release_path=$(python3 -c 'import json; print(json.load(open("/srv/recordbench/installation.json"))["release_path"])')
docker compose --env-file /srv/recordbench/compose.env \
  -f "$release_path/compose.yaml" -f "$release_path/compose.local-accounts.yaml" stop
./install install --root /srv/recordbench --resume --non-interactive --no-color
./install doctor --root /srv/recordbench
```

Sign in again and open the **original** practice matter: its two records, saved
note and exported note must survive. Repeat the browser runner with
`--allow-previous-synthetic-runs` added to the same command. This second run
creates another synthetic matter and two reviewers; it does not itself prove
the first matter's contents survived. Retain its separate JSON result. A planned
stop/resume checks service recovery; a host reboot remains a separate `pending`
phase unless an actual reboot and the same persistence readback were performed.

## 4. Verify encrypted backup and an isolated restore

Use [Storage and backup](STORAGE_AND_BACKUP.md) and keep the repository,
recovery-key directory and restore target outside the node and outside one
another. A single disposable Linux box can run a **local encryption/restore
drill** with the existing explicit `--allow-local-backup` option. It proves the
tooling, not recovery from loss of that box. Record that shared failure domain;
an independent backup/replacement-host test remains separate.

For that synthetic local drill, the administrator creates dedicated parents:

```bash
sudo install -d -m 0700 -o recordbench -g recordbench \
  /srv/recordbench-alpha-backup /srv/recordbench-alpha-recovery /srv/recordbench-drills
```

As the service account, with background work finished:

```bash
./install backup --root /srv/recordbench \
  --repository /srv/recordbench-alpha-backup/restic \
  --recovery-key-output /srv/recordbench-alpha-recovery/restic-password \
  --allow-local-backup
./install restore --root /srv/recordbench \
  --restore-target /srv/recordbench-drills/restore-drill-001
./install doctor --root /srv/recordbench
```

For independent backup storage, use verified mounted repository/recovery parents
from the storage playbook instead and omit the local-test option. Do not assume
that a directory named `/mnt/backup` is a mounted independent filesystem.

Leave the restore target absent before running it. Record successful encrypted
backup, SQLite inventory/integrity and PostgreSQL dump-list verification from
the restore receipt. A deferred or failed backup does not pass. This drill
restores and checks files in isolation; it does **not** import PostgreSQL into a
running replacement node or exercise restored browser sign-in, grants and export.
Keep those two recovery phases explicitly `pending` unless they were separately
performed with the matching release and isolated storage. Never attach drill
data to the live node to simulate a clean restore. Retain the matching candidate
distribution: container images and release capsules are not in the backup.

## Return this concise receipt

Use `passed`, `failed`, `blocked`, `pending` or `skipped` for each phase. Every
status other than `passed` needs a short reason; skipped work is not a pass.
Attach the browser JSON receipt(s) and installer diagnostics JSON after checking
them for unexpected identifying data. Keep raw command output, addresses,
usernames, secrets, certificates and screenshots private.

```text
Candidate SHA / clean checkout:
Installed release ID / observed health release ID:
Ubuntu version / architecture / native or VM:
CPU count / RAM and effective limit / swap:
Docker version / Compose version / storage driver:
Free GiB (Docker, node): before / after build / after first export:
Cache state: images+layers [cold/warm]; signatures [cold/mirror/import/warm]; browser [cold/warm]
Timings, seconds: host setup / prepare / signatures / resume-to-ready / browser total:
First verified export, seconds from install start: [observed value or pending; state measurement method]
Preflight / prepare-only / initial resume+doctor:
TLS+installed browser positive journey / three-account negative matrix:
Laptop SSH+Firefox trust and manual review:
Stop+resume / original-work persistence / repeated browser matrix:
Host reboot+original-work persistence:
Encrypted backup / isolated restore integrity / local or independent storage:
Restored PostgreSQL import / replacement-node browser+access+export:
Manual interventions: [count; short content-free action and added duration for each]
Unexpected failures: [bounded error codes; no raw logs]
Remaining pending/skipped/blocked work:
```

Do not label the candidate accepted while required phases remain incomplete.
Report the exact boundary reached so a maintainer can distinguish a usable CPU
alpha node, a recovered installation, and a fully verified replacement host.
