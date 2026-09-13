# Linux alpha onboarding

Status: implementation candidate; independent fresh-Linux acceptance is pending.
Source baseline: `d43e142769b5d57a901fb58439bf841ed954b8b4`.
This is cruise step 10, not a supported-release or deployment receipt.

## Outcome

An unfamiliar person should reach their first exported synthetic matter using
public instructions, with zero undocumented commands and zero maintainer
interventions. A contributor should run tests and open a synthetic development
workspace without installing an application node.

README now offers two entry points:

- [Try RecordBench](TRY_RECORDBENCH.md): CPU basic review, local accounts,
  practice files, temporary evaluation TLS and an SSH browser tunnel.
- [Contribute code](../CONTRIBUTING.md): repeatable dependency setup, checks,
  publication-hook guidance and a disposable `make dev` preview.

The first acceptance target is a conventional Ubuntu 24.04 x86-64 host or VM.
A conventional Debian host is a later validation target; nested Docker hosts
remain a separate advanced route. These are validation choices, not claims that
an untested host is supported. The current 16 GB RAM/150 GB disk planning figures
and 100 GiB runtime safety reserve remain unchanged.

## Candidate changes

| Concern | Implemented behavior | Evidence boundary |
| --- | --- | --- |
| Browser asset origin | Same-origin CSS, JS and icon paths preserve TLS, external port and supported path prefix. | Synthetic origin regressions and actual Chrome app journeys pass; installed gateway acceptance remains separate. |
| Explicit account selection | Empty required choices and display name plus username in pickers, roster and confirmation. | Duplicate-name/non-first selection, unassigned denial and existing-session revocation have synthetic and browser coverage. Stable principal authorization remains unchanged. |
| First install | Short host/service-account guide, complete password-only CPU command, prepare/resume, doctor, evaluation TLS and SSH tunnel. | Local protected-key, trusted-TLS and actual tunnel tests pass. The unfamiliar-operator and Firefox trust journeys remain pending. |
| Diagnostics | Fixed Docker failure categories, storage-ancestry reasons, process/cgroup memory advisories and content-minimized JSON. | Synthetic permission, capacity and privacy tests. Memory is explicitly a process observation; remote engine capacity is not inferred. |
| Selected readiness | Mandatory source review, storage and malware scanning plus selected optional capabilities determine health. CPU shows unselected models neutrally. | Profile combinations and required-service failures tested. Transcription's existing readiness interface does not prove worker execution. |
| Antivirus preparation | A bounded visible signature stage precedes scanner startup; header build age replaces filesystem timestamp freshness. | Synthetic failure categories plus actual pinned-engine update and empty-volume download. These container probes are not a whole-node install. |
| Antivirus recovery | Typed mirror/proxy config and signed CVD import into a stopped node; protected snapshots, offline signature/engine checks, serialization and durable interrupted-import refusal. | Synthetic failure regressions and actual signed import with networking disabled. Ongoing update access and a live private mirror remain separate host evidence. |
| Installed browser check | Standard-library runner downloads the existing verified browser pins and exercises the real HTTPS gateway, release readback, upload/search/source/note/export and three-session access matrix. | Helper-level Chrome rehearsal and TLS/unit tests; final Linux NSS and installed gateway receipt pending. |
| Contributor preview | `make dev` opens a loopback-only, temporary synthetic app and cleans up on exit. | Actual browser upload/search/note/export and startup/termination tests; no claim of installed-node security or scanner validation. |

See [antivirus recovery](ANTIVIRUS_RECOVERY.md),
[installation diagnostics](INSTALL_DIAGNOSTICS.md),
[browser origins](BROWSER_ASSET_ORIGIN.md),
[account selection](TEAM_IDENTITY_CHOICES.md), and
[installed browser acceptance](INSTALLED_CPU_ACCEPTANCE.md) for detailed contracts.
No schema, model revision, public service binding or trusted-proxy identity
boundary changes are included.

## Evidence that closes this work

Give the separate Linux agent the exact candidate commit and
[Linux acceptance handoff](LINUX_ALPHA_ACCEPTANCE.md). Run on a disposable host
with fresh node state, no inherited signature volume and explicitly recorded
image/build caches. Follow the public guide. Required outcomes include:

- Trusted browser sign-in through the installed HTTPS gateway, including the
  headless tunnel and working styles/scripts.
- Both approved synthetic uploads, processing, word and phrase search, original
  source inspection, saved note and verified export.
- Administrator, deliberately selected teammate and unassigned account in
  separate sessions; exact roster, allowed access, unassigned denial, then
  revocation in the teammate's existing session.
- Preparation/resume and ordinary restart without losing sources or identities;
  encrypted backup and a separate clean restore drill, with the limits of that
  drill recorded. A file-integrity restore is not restored-browser acceptance.
- Antivirus recovery/failure evidence that distinguishes seeded import, fresh
  download and future updater access. Preserve cooldowns and scanner isolation.
- First useful review/export time, downloaded bytes where measurable, RAM/disk
  observations for both node and engine storage, retries and manual intervention.
  Unknown measurements and skipped phases must remain explicit.

Run the installed check whenever installer, Compose, gateway or startup
dependencies change and on each proposed alpha candidate. Provision enough disk
and memory for the selected policy; do not lower reserves to fit the host.
Keep periodic truly cold runs distinct from cached runs. This candidate supplies
the external-host runner and handoff; it does not attach private infrastructure
to public CI or claim a hosted cold-install lane already exists.

The source changes need their ordinary publication, unit, hosted review and
maintainer gates as well. Mac-native failures must be compared against the exact
upstream baseline and disclosed; baseline equality does not pass Linux acceptance.

## Follow-up release scope

Prebuilt CPU alpha images remain separate work. Immutable images and a versioned
manifest could remove per-host source builds after dependency, licensing, SBOM,
scan, checksum and provenance requirements are met. Keep source builds for
contributors and rerun the installed journey on the exact released artifact.
Use measured installation peaks to decide whether a smaller synthetic evaluation
profile is feasible; reducing the storage reserve alone does not establish one.
