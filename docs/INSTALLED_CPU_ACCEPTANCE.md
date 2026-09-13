# Check the installed CPU browser journey

Run `scripts/accept-installed-cpu.py` against a new **synthetic-only** CPU
evaluation node after installation has finished. It exercises the actual HTTPS
gateway and application using three independent accounts in isolated browser
sessions, with at most two browsers running together. The administrator completes
the main workflow alone, apart from sequential first sign-ins that register each
new reviewer in the team picker. Each registration browser closes immediately.
The unassigned reviewer later signs into a fresh browser for denial checks and
closes before the selected reviewer opens; the selected reviewer remains in
the same fresh session for both permitted access and denial after revocation.
There are five browser launches in total. This is
separate from the disposable application browser tests and from cold-install,
resume, backup and clean-restore checks.

The runner uses Python 3.11 or newer and the standard library. It automatically
downloads and verifies the existing SHA-256-pinned Chrome and ChromeDriver pair
in `config/browser-testing.json`; no Node, Playwright or Selenium setup is needed.
The host still needs the operating-system libraries required by Chrome. Run as
an unprivileged user, with the normal browser sandbox enabled. The Linux x86_64
path is the installed-node acceptance target; a local Mac browser rehearsal does
not establish Linux installation success.

On Linux, Chrome uses `--disable-dev-shm-usage` to place shared-memory backing
files in the runner's private temporary directory. This avoids depending on a
container's small `/dev/shm` mount. The [pinned Chromium implementation](https://github.com/chromium/chromium/blob/153.0.8010.36/base/files/file_util_posix.cc)
honors the runner's isolated `TMPDIR`; normal sandbox and TLS checks remain
enabled. This still requires available memory and temporary storage and does
not diagnose the cause of a previous crash. Other platforms retain their
existing browser options.

## Start a check

Use the same reviewed checkout as the installation, with browser account
management enabled. The target must contain no existing matters and only the
initial local administrator. The acknowledgment confirms that the entire node
contains only invented evaluation material; it does not authorize the runner to
clear or replace existing work.

```console
python3 scripts/accept-installed-cpu.py \
  --url https://recordbench.example.test:8443 \
  --node-root /srv/recordbench \
  --admin-username synthetic.admin \
  --ca-file /secure/path/evaluation-ca.crt \
  --acknowledge-synthetic-evaluation
```

The password is prompted privately. For an unattended run, use
`--admin-password-file` pointing to an owned, regular, nonsymlink mode-0600 file.
No password argument or password environment variable is supported. The runner
creates two reviewer accounts with unique names and random passwords held only
in memory. It leaves the synthetic accounts, matter, two sources and saved note
available for operator inspection; it removes the granted reviewer's access as
part of the check. It does not delete the installation or reset any account.

`--node-root` reads the expected release from `installation.json`. When running
from another machine, supply `--expected-release-id` copied from that file. The
runner compares it with the application's actual `/health` `release_id` before
creating accounts or a matter. A source checkout SHA is not a release identifier.
The receipt distinguishes the runner's Git commit from the expected and observed
installed release IDs. An optional supplied expectation must agree with local
node metadata when both are present.

## TLS trust

The URL must be an HTTPS origin, including the external port when nondefault.
It cannot contain credentials, a path, query or fragment. The runner checks the
certificate chain and hostname and refuses a redirected health endpoint.
The supplied CA is read once from a bounded regular nonsymlink file; the health
probe and private browser trust store use that same snapshot.

For a publicly trusted certificate, omit `--ca-file`. For a private evaluation
CA, supply a single PEM certificate. On Linux the runner imports it into its own
temporary NSS database using `certutil`; install `libnss3-tools` on Debian/Ubuntu
or `nss-tools` on Fedora if needed. It does not modify system trust or an existing
browser profile. The [Chromium certificate documentation](https://chromium.googlesource.com/chromium/src/+/master/docs/linux/cert_management.md)
identifies the NSS shared database location used by the pinned browser.

Both the health probe and browser must trust the configured HTTPS address. A
certificate error remains a failed phase; the runner never enables insecure
certificate acceptance, disables hostname checks or bypasses the browser
sandbox. For an SSH tunnel, use the certificate's hostname and ensure it resolves
to the tunnel endpoint from the machine running the browser.

## What passes

The fixed phase list covers:

- TLS verification and exact installed release readback, overall healthy status,
  ready storage/source review/malware scanning, and all three optional model
  capabilities explicitly unselected for the CPU profile.
- Real local sign-in forms, including their normal login challenge. The runner
  focuses an editable input, clears it only when nonempty, types through
  WebDriver and verifies the resulting value without recording that value.
- An empty synthetic node, loaded same-origin styles and a working Activity drawer.
- Two new reviewers with the same display name and distinct sign-in usernames.
- Upload of the two exact bundled files in `examples/synthetic-alpha/`, ordinary
  word search for `lantern`, exact phrase search for `blue lantern`, and original
  source review.
- A saved `battery count difference` note and its verified contents inside
  `notebook/matter-notebook.md` in the downloaded matter ZIP.
- Explicit selection of a non-first reviewer by its visible account label,
  matching confirmation/roster, permitted reviewer access, unassigned-account
  denial and denial in the same reviewer session after removing its last grant.

The source fixtures must match their expected hashes and are copied into private
scratch storage before browser setup, so later checkout edits cannot change the
uploaded bytes. The runner refuses other
files rather than treating operator material as a test fixture. It does not
enable models, alter a storage reserve, change service configuration or invoke
container commands. Model quality and confidential-workload readiness remain
outside this CPU browser check.

## Receipt and repeat runs

Standard output contains one JSON object. `passed` is true only when every fixed
phase passed; the exit status is zero only then. A failure names the phase and a
fixed failure code. Null counts mean the corresponding creation/upload phase
did not finish verification; partial synthetic work may remain on a failed run.
The receipt contains no URL, hostname, account names, password, cookie, source
text, exported note, filesystem path or raw exception.
When a WebDriver command fails, `webdriver` adds only an allowlisted protocol
error, HTTP method and command operation such as `element_clear` or
`element_type`. Unknown error text becomes `unrecognized_error`; response
messages, stack traces, selectors and session/element identifiers are omitted.
The fixed vendor statuses `tab crashed`, `disconnected`, `chrome not reachable`
and `target frame detached` are retained directly, without an external wrapper.
A `tab crashed` result identifies a browser failure, not its underlying cause.
Input failures remain failures; the runner does not retry typing or submit a
form after a failed clear, focus or value check.
`phase_seconds` records monotonic elapsed seconds for each attempted phase;
unattempted phases remain null. `first_export_seconds` measures from runner start
through verification of the saved note in the ZIP, including password entry and
browser setup/download time; it stays null when export verification fails.

Browser profiles and downloaded exports exist only inside disposable private
scratch storage. Exports are inspected in bounded memory without extraction.
No screenshots, DOM snapshots or browser logs are collected. Handled errors,
SIGINT and SIGTERM close browser process groups and remove private scratch state.
Forced termination such as SIGKILL or host failure cannot run cleanup; inspect
and remove any leftover runner scratch directory privately before sharing evidence.
Share the JSON receipt first when asking for help.

By default another run refuses an already populated node. To repeat on a node
containing only this runner's earlier synthetic work, add
`--allow-previous-synthetic-runs` alongside the acknowledgment. The runner still
refuses unknown matter/account names and more than ten prior matters or twenty
reviewer accounts, unrecognized administrator-page structure, and any retained
failed-deletion work. It always creates a new unique practice matter and accounts.
For offline use, `--archives` selects an existing directory containing the exact
Chrome and ChromeDriver ZIP filenames from the pin manifest; hashes are still
verified before extraction or execution.

## Maintainer validation

`tests/test_installed_cpu_acceptance.py` checks URL/identity input boundaries,
protected password files, fixed source hashes, a real local TLS server with
trusted/untrusted/mismatched-host certificates, redirect refusal, temporary CA
import, populated-node refusal, bounded export validation and content-free
failure receipts, monotonic timing, and real signal/child-process cleanup.
Session-lifecycle regressions check the two-browser limit, independent reviewer
logins and revocation in the same selected session; input and protocol tests
cover empty-field handling and redaction of WebDriver HTTP error responses.
Browser helper rehearsal on a disposable app is additional
evidence. The final installed Linux receipt must come from the actual x86_64
host, after its normal cold-install and recovery gates.

### Control connection and final revision check

Before sending any WebDriver HTTP bytes, the runner verifies that the connected
TCP peer belongs to its own ChromeDriver child using kernel socket ownership
(`/proc` on Linux, the system `lsof` on macOS). Every new connection repeats the
check; unavailable evidence or an exited driver fails closed. A replacement
listener cannot inherit an established connection. This authenticates the server
against local port impersonation; use the dedicated trusted service account and
host, since root or processes able to control that account remain trusted.

After the complete browser journey, the runner repeats verified HTTPS health,
readiness and the exact expected release comparison before reporting success.
A changed release or unavailable health makes the receipt fail. The before/after
checks detect a changed final revision; they are not continuous attestation of
every request or proof that no transient update and rollback occurred.
