# Linux alpha candidate validation

Local implementation evidence recorded 2026-09-12. This is not an installed
Linux acceptance receipt or release approval. The comparison baseline was
`d43e142769b5d57a901fb58439bf841ed954b8b4`.

## Application and installer

The integrated installer, handoff, antivirus, diagnostics, selected-capability,
asset-origin, account-choice, development-preview, TLS and branding suites passed
620 tests at the integration checkpoint. The native macOS application suite then
reported 2,936 passed, 125 failed and 9 skipped. A clean detached checkout of the
exact baseline reported 2,820 passed, the same 125 failed test IDs and the same
9 skipped tests. There were no candidate-only or baseline-only failure IDs.
These failures remain failures; comparison isolates platform limitations and
does not pass the required Linux test gate. The transcription suite passed all
194 tests.

The protected TLS directory, preview startup interruption and installed browser
runner were subsequently strengthened through independent review and focused
regressions. The final combined antivirus/helper/installed-runner suite passed
97 tests. Independent installed/existing-browser-runner checks passed 80 tests,
and the complete three-browser helper rehearsal passed again after review fixes.
The broad checkpoint counts above must not be described as a final all-green suite.

Standard, Kerberos and dedicated-local-account Compose graphs validate.
Compilation and diff-whitespace checks pass. The publication tree and full
outgoing history must pass before the candidate branch is transmitted.

## Browser and evaluation TLS

Real Chrome journeys against disposable synthetic applications exercised
same-origin assets and Activity, duplicate-display-name account selection,
unassigned-user denial and revocation in an existing browser session. The
contributor preview exercised upload, word search, original-source review,
saved note and ZIP contents. Desktop/mobile screenshots were inspected locally.

Temporary evaluation CA and leaf generation passed chain, hostname, default
untrusted-certificate refusal and protected-directory tests. A local disposable
SSH server and verified-host tunnel carried a trusted TLS connection. These
checks do not prove the separate Firefox profile/trust UI on the unfamiliar
operator's laptop.

The new installed browser runner's full helper journey was rehearsed using three
real Chrome sessions against a disposable application. Its HTTPS fixture tests
check real certificate trust and refusal cases. The installed x86-64 gateway,
Linux NSS integration and host browser policy remain external acceptance gates.

## Follow-up candidate corrections

Browser acceptance must not depend on starting all three Chrome sessions before
administrator sign-in. The revised runner starts the administrator first,
signs each new reviewer in once to register its principal and closes those
browsers, then uses fresh independent sessions for the access matrix. It checks
the unassigned account and closes that browser before opening the selected
reviewer's browser. That selected session remains alive for both allowed access
and revocation. Initially empty inputs no longer receive an unnecessary WebDriver
clear command; focus and exact entered values remain checked. WebDriver failures
report only allowlisted error, method and operation fields. These changes do not
establish that memory pressure caused a particular browser failure, or turn an
incomplete installed journey into a pass.
The corrected installed/existing browser-runner suite passed 95 tests. A full
local Chrome helper rehearsal passed all journey phases, including first-login
registration and the final access matrix, while asserting five total profiles
and at most two live browsers. The rehearsal used a disposable synthetic app;
it does not establish installed Linux HTTPS, NSS or browser-sandbox acceptance.

A separate clean-source comparison reproduced a capsule fingerprint mismatch:
the installer hashed a nested pytest cache that its copy operation excluded.
At `854ab326fdd7566614c8da37a8d1fe2302e56f3d`, the clean archive produces
`0.1.0-alpha.2-b9fe419d710c`. That is the correct clean-source capsule for that
revision. Hashing and copying now share the same cache filter. Synthetic tests
cover nested caches, source changes and symbolic-link refusal even inside an
excluded directory. Every later candidate needs its own clean-archive ID.
The combined installer, first-run handoff, diagnostics, antivirus and evaluation
TLS suite passed 589 tests after the cache correction.

The antivirus guide now includes acquisition from an empty donor directory,
complete signed CVDs, checksum transfer and the existing offline verification
and import. A donor with working upstream access is still required. Success
using imported signatures leaves the default first-download and future refresh
lanes unproven on the target host.
The documented donor FreshClam command was exercised with the pinned amd64 image
under emulation: an empty directory downloaded all three complete CVDs and passed
all three engine load tests in approximately 39 seconds. Network-disabled
`sigtool` verification and signed-header freshness checks also passed. This is
donor component evidence; cross-host SSH transfer and native installed acceptance
remain separate checks.

## Antivirus engine evidence

The existing pinned `clamav/clamav` image was exercised as linux/amd64 under
emulation on a macOS-hosted Linux VM. This is bounded component evidence:

- FreshClam updated the image's existing database and load-tested the results.
- A separate empty signature volume downloaded all three complete CVD databases
  and passed their engine tests with the Compose updater's existing 1 GiB/1 CPU
  limits. It completed in approximately 72 seconds without an OOM termination.
- The offline import helper verified the three actual signed CVDs with `sigtool`,
  loaded them and scanned its harmless sample with networking disabled. The
  resulting header-age health check passed.

Synthetic regressions also cover blocked/timeout/cooldown classification, stale
headers despite new filesystem timestamps, unsafe ancestry/files/configuration,
concurrent antivirus operations, every active-container state, invalid signature
rejection before replacement and the durable incomplete-import marker.
A current signed offline bundle does not prove future updater connectivity or
that no newer upstream database exists. A live private mirror/proxy and whole
installed-node recovery still need target-host evidence.

## Remaining acceptance

Follow [the Linux-agent handoff](LINUX_ALPHA_ACCEPTANCE.md) at the full candidate
commit. Record cold/cache state, normal storage reserves, prepare/resume,
trusted browser/export/access checks, restart and encrypted backup/restore.
Retain explicit pending/blocked states for every unrun step, including booted
restored-browser acceptance if only the integrity drill was performed.
Hosted code/security review, required CI and maintainer acceptance also remain
separate gates. No release tag, production image or deployment is created by
these source changes.
