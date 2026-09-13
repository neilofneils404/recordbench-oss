# Antivirus preparation and recovery

RecordBench starts its signature updater before starting the scanner and app.
The installer gives this signature-readiness stage three minutes, then retains
the node and reports a fixed failure category with recovery instructions. The
updater may continue its own supported retry/cooldown schedule after the installer
returns. Repeated installer retries do not remove FreshClam cooldown state.

The updater has download access; the scanner remains on the private service
network and the offline import helper has no network. Missing, invalid or stale
daily databases, or an interrupted import, block readiness. Freshness uses the
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

## Import signed databases while offline

On a machine with permitted updater access, obtain the official **signed CVD**
files using FreshClam or a maintained CVDUpdate mirror. Transfer `main.cvd`,
`daily.cvd` and `bytecode.cvd` into one protected directory accessible to the
service account. The directory and its ancestors must be root/service-owned,
protected against other writers and free of symlinks. Each file must be a regular,
non-shared-writable file of at most 512 MiB. Keep the bundle outside the checkout.
Unsigned/custom databases and patched CLD files are not accepted as import inputs.

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
startup failure reporting without copying raw logs into errors. Installed-node
acceptance additionally needs a real successful update, scanner health and
synthetic upload on the intended Linux host.
