# Antivirus preparation and recovery

RecordBench starts its signature updater before starting the scanner and app.
The installer gives this signature-readiness stage three minutes, then retains
the node and reports a fixed failure category with recovery instructions. The
updater may continue its own supported retry/cooldown schedule after the installer
returns. Repeated installer retries do not remove FreshClam cooldown state.

The updater has download access; the scanner remains on the private service
network and the offline import helper has no network. Missing, invalid or stale
daily databases, or an interrupted import, block readiness. Main, daily and
bytecode databases must all be nonempty regular files, not symlinks or writable
by group/other users; either the supported CVD or CLD form is accepted. Freshness uses the
database header's reported build epoch within the preceding 72 hours, with five
minutes of clock tolerance. Copying or touching a file does not refresh that age.
FreshClam verifies updates and load-tests downloaded databases. The import path
also verifies signed CVD content and loads it with the pinned engine. Offline
checks cannot establish that no newer upstream database exists.

## First download

Use the ordinary install/resume command. A generic curl/wget request is not a
FreshClam test. If the download is blocked or times out, inspect the updater's
local logs using the saved node coordinates in the installation playbook.
Keep raw logs private. Correct DNS/TLS/egress, honor cooldowns, or select a private
mirror/proxy. Do not change timestamps, disable malware scanning, or delete
FreshClam's cooldown metadata to force startup.

If this is your only machine and its network cannot reach the official updater,
an approved mirror/proxy or a trusted donor with current signed databases is
required. There is no way to obtain current trusted signatures entirely offline
without one of those inputs. RecordBench does not bundle current signatures or
provide a hosted mirror. The procedures below do not bypass CDN restrictions.

## Configure an approved mirror or proxy

Run these commands as the dedicated service account. The node must be prepared
and stopped: use `--prepare-only` for a new install. If services are running, the
antivirus command refuses changes and prints the exact node-specific Compose
stop command. It does not stop another node or change global Docker settings.

```bash
./install antivirus --root /srv/recordbench \
  --antivirus-mirror https://mirror.example.test/clamav
./install install --root /srv/recordbench --resume
./install doctor --root /srv/recordbench
```

The mirror must serve the official complete CVD/CLD databases and support HTTP
Range requests. This configuration uses FreshClam `PrivateMirror` with patch
updates disabled. Follow the upstream
[private mirror procedure](https://docs.clamav.net/appendix/CvdPrivateMirror.html).
Deploy and maintain that mirror outside the public source tree.

For an HTTP proxy, use `--antivirus-proxy http://proxy.example.test:3128` instead,
or provide both options together. URLs cannot contain credentials, queries,
fragments or configuration directives. Authenticated proxies and custom CA
injection are not supported by this first interface. The operator controls
the private endpoint; none is committed to the portable tree.

Each configure command replaces the complete mirror/proxy selection. Omitting a
previous proxy removes it; omitting a previous mirror restores the public source.
`--reset-antivirus` explicitly restores the default public source with no proxy.
`--dry-run` validates the selection without changing files or service state.

The generated configuration is an owner-only file under the node's configuration
directory and is included in its ordinary configuration backup. Resume/update
validate its exact supported directives and canonical path. The scanner never
receives that network configuration. Update rollback retains the existing node
configuration; a mirror change itself is explicit and is not undone by an app
update. On older installed releases without this recovery helper, first follow
the ordinary reviewed update procedure.

## Obtain a complete signed bundle on a donor

Use a Linux x86-64 donor with Docker access and a network permitted to run
FreshClam. It can be another machine you administer; it does not need a running
RecordBench node or any existing signature volume. First correct any known
network block or honor an existing cooldown; a new temporary directory is not a
way to reset a donor's rate limit. For ongoing distribution to several nodes,
use the upstream [maintained private mirror procedure](https://docs.clamav.net/appendix/CvdPrivateMirror.html)
instead of repeatedly creating fresh bundles.

The commands below use the image digest pinned in this candidate's `compose.yaml`.
The explicit empty database directory avoids relying on databases preloaded in
an image. [FreshClam downloads complete databases when that directory is empty](https://docs.clamav.net/manual/Usage/SignatureManagement.html).
Its [configuration and `--datadir` options](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.4/docs/man/freshclam.1.in)
select that directory. `ScriptedUpdates no` keeps this export in full CVD form;
`TestDatabases yes` retains engine load tests. Allow disk space for the download
and export copy, and memory for those tests; this example caps the container at
4 GiB. Run as an ordinary donor account with Docker access, not as root:

```bash
set -e
test "$(id -u)" -ne 0
umask 077
clamav_image='clamav/clamav:stable@sha256:594d54aff5ad3b1a5211d67cdc6d49a9a332276da35d821c3dd4cf6c4cdf6237'
docker pull --platform linux/amd64 "$clamav_image"
donor_dir=$(mktemp -d "$HOME/recordbench-cvd-donor.XXXXXX")
printf 'Retain for any retry: %s\n' "$donor_dir"
mkdir -m 0700 "$donor_dir/db"
cat > "$donor_dir/freshclam.conf" <<'EOF'
DatabaseMirror database.clamav.net
ScriptedUpdates no
TestDatabases yes
Bytecode yes
ConnectTimeout 15
ReceiveTimeout 60
MaxAttempts 2
LogTime yes
EOF
docker run --rm --name recordbench-cvd-donor --platform linux/amd64 \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 4g --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m \
  --mount "type=bind,source=$donor_dir,target=/donor" \
  --entrypoint freshclam "$clamav_image" \
  --config-file=/donor/freshclam.conf --datadir=/donor/db --stdout
```

Continue only after a successful exit and all three database tests pass. This
container only runs FreshClam; it publishes no port and mounts no node volume.
If it fails, retain `donor_dir`, including `db/freshclam.dat`, and diagnose locally.
After the reported cooldown or network correction, retry only the `docker run`
command against the **same** directory. Do not recreate it to force downloads,
use curl/wget for the CVDs, or disable database tests. See the upstream
[FreshClam error guidance](https://docs.clamav.net/faq/faq-freshclam.html).
If you opened a new shell, set `donor_dir` to the printed path and `clamav_image`
to the same pinned value before retrying.

Next verify all three embedded CVD signatures without network access.
[`sigtool --info` checks the checksum and digital signature](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.4/docs/man/sigtool.1.in)
as well as displaying the database version and build time:

```bash
docker run --rm --platform linux/amd64 --network none \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,source=$donor_dir,target=/donor,readonly" \
  --entrypoint sh "$clamav_image" -eu -c '
    for name in main daily bytecode; do
      sigtool --info "/donor/db/$name.cvd"
    done
  '
```

Require `Verification OK` for each file. Check the reported daily build time
against a correct UTC clock: it must be no more than 72 hours old or five minutes
in the future. The target import repeats this check from the CVD header after
signature verification; filesystem timestamps are irrelevant. Record the three
versions and daily build time for the recovery receipt. CLD files cannot be
renamed into signed CVDs.

Create a transfer directory containing only the three verified files and their
SHA-256 manifest. The updater has exited, so these copies cannot be changed by
an ongoing update:

```bash
mkdir -m 0700 "$donor_dir/export"
cp -- "$donor_dir/db/main.cvd" "$donor_dir/db/daily.cvd" \
  "$donor_dir/db/bytecode.cvd" "$donor_dir/export/"
(
  cd "$donor_dir/export"
  chmod 0600 main.cvd daily.cvd bytecode.cvd
  sha256sum main.cvd daily.cvd bytecode.cvd > SHA256SUMS
)
```

## Import signed databases while offline

Use your existing, verified SSH administrator destination for the target host;
`alpha-host` below is a placeholder for that SSH alias. The dedicated service
account does not need SSH access. From the donor, create a new private transfer
directory in the target administrator's home and copy the four explicit files:

```bash
ssh -o StrictHostKeyChecking=yes alpha-host \
  'umask 077; mkdir -m 0700 "$HOME/recordbench-signature-transfer"'
scp -o StrictHostKeyChecking=yes \
  "$donor_dir/export/main.cvd" "$donor_dir/export/daily.cvd" \
  "$donor_dir/export/bytecode.cvd" "$donor_dir/export/SHA256SUMS" \
  alpha-host:recordbench-signature-transfer/
```

On the target, as its administrator, verify transfer integrity and create a new
protected import directory. Both destination directories deliberately refuse an
existing name; choose a new name and adjust the commands for a later bundle.

```bash
set -e
cd "$HOME/recordbench-signature-transfer"
sha256sum --check --strict SHA256SUMS
sudo -u recordbench mkdir -m 0700 /var/lib/recordbench-home/signature-import
sudo install -m 0600 -o recordbench -g recordbench \
  main.cvd daily.cvd bytecode.cvd SHA256SUMS \
  /var/lib/recordbench-home/signature-import/
sudo -iu recordbench
```

The manifest checks transfer integrity; the pinned engine's CVD verification
establishes signature authenticity. A removable-media transfer can use the same
four files and integrity check if SSH is unavailable. Keep the bundle outside
the checkout. Its directory and ancestors must be root/service-owned,
protected against other writers and free of symlinks. Each file must be a regular,
non-shared-writable file of at most 512 MiB.
Unsigned/custom databases and patched CLD files are not accepted as import inputs.
Return to the candidate checkout as the service account. The prepared node must
be stopped; if needed, the command prints its exact stop command. Then import:

```bash
./install antivirus --root /srv/recordbench \
  --import-signatures /var/lib/recordbench-home/signature-import
./install install --root /srv/recordbench --resume
./install doctor --root /srv/recordbench
```

The installer snapshots only these three files, rejects stale/future daily
headers, and checks that the inputs did not change during copying. A temporary
networkless container verifies their signatures with `sigtool`, loads the complete
database set and scans a harmless built-in text sample before replacing files in
this stopped node's signature volume. This needs memory for an engine load and
temporary space for the source snapshot and database staging; it does not reduce
the ordinary storage reserve. The source files are left intact.

An unsuccessful verification leaves the prior databases unchanged. Interruption
during replacement leaves a pending marker that blocks signature readiness;
rerun a complete valid import to finish all three files before resuming. The
import leaves FreshClam cooldown metadata alone. It never imports account state,
application sources or model weights.

Successful import proves that the pinned engine loaded the imported database
content. It does not prove ongoing download access. Arrange a working updater
route before the daily database ages out; the readiness check will block again
when its reported age exceeds policy. Keep a separate fresh-download acceptance
receipt rather than describing a seeded import as a clean download.

## Validation

Synthetic regressions cover unsafe source files and configuration, stale headers
with fresh filesystem timestamps, incomplete imports, signature-verification
failure before replacement, refusal to mutate a running node, and bounded
startup failure reporting without copying raw logs into errors. Mirror, proxy,
combined and reset commands also exercise real configuration/environment writes,
including replacement of an existing selection and canonical validation for
resume. Installed-node acceptance additionally needs a real successful update,
scanner health and synthetic upload on the intended Linux host.
