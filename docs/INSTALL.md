# Installation playbook

For a source checkout used to write code and run tests, start with
[contributor setup](../CONTRIBUTING.md#set-up-a-development-checkout). The playbook
below installs an application node; `make bootstrap` prepares a development
environment and does not deploy the application.

## Hardware and capability profiles

RecordBench targets a modern x86-64 Linux host with Docker Engine and Docker
Compose v2. The figures below are starting targets for alpha evaluation, not
validated minimums:

| Intended use | CPU | RAM | NVIDIA GPU | Free SSD before matter data |
| --- | ---: | ---: | --- | ---: |
| CPU evaluation | 8 cores | 16 GB | none | 150 GB |
| Local document review | 12 cores | 32 GB | 1 GPU with 16 GB VRAM | 200 GB |
| Every-source checks and media | 16 cores | 64 GB | 1 GPU with 24 GB VRAM | 300 GB |

These targets do not guarantee collection size, speed, or concurrency. More
sources, longer recordings, and more simultaneous users need more capacity.
Consult [release readiness](RELEASE_READINESS.md) before treating a
configuration as supported. Free-space targets cover application images,
models, temporary processing, and the configured safety reserve; matter
contents require additional local or NAS capacity.

The installer exposes four capability profiles:

| CLI value | What it enables |
| --- | --- |
| `none` | CPU evaluation with intake, extraction, OCR, word search, source review, and exports |
| `review` | learned retrieval, reranking, and cited local generation |
| `transcription` | media transcription without the review-model services |
| `all` | document review plus transcription and optional diarization |

GPU profiles require NVIDIA compute capability 7.5 or newer and the NVIDIA
Container Toolkit. The intended deployment model supports one suitable GPU,
with additional GPUs separating generation, transcription, and retrieval work.
Each configuration still needs deployment validation. Advanced placement
controls are documented in [Models](MODELS.md).

The installer never opens a public port by default. Its initial listener is
`127.0.0.1:8443`; a LAN bind requires an explicit address and an existing
organization-trusted certificate.

## Before installation

1. Choose a dedicated node state root. Do not use `/`, a home directory, or the
   root of a shared NAS export.
2. Choose matter storage. A host-mounted NAS path is supported when it is stable,
   writable by the RecordBench UID, and dedicated to this installation.
3. Decide between local accounts, OIDC, or Kerberos/Windows Integrated
   Authentication.
4. Obtain DNS and a trusted TLS certificate for staff access.
5. Choose transcription modules. Ungated ASR and English/Spanish alignment can
   be staged independently. Enabling Community-1 diarization additionally
   requires accepting its Hugging Face terms and a read-only token for the
   one-time staging step.
6. Decide where the encrypted restic repository and independent recovery key
   will live.

## Inspect prerequisites without installing

Run this first as the dedicated non-root service account on the intended Linux
host. It does not prompt, create directories, write probe files, download models,
start containers, or change permissions:

```bash
./install preflight --root /srv/recordbench --models none --no-color
./install preflight --root /srv/recordbench --models review --json
```

Supply the same `--storage-root`, `--server-name`, `--bind-address`, TLS, model
and GPU-selection options you intend to use for installation. Quote paths
containing spaces.
Omitted options select `/srv/recordbench`, storage beneath it, CPU evaluation,
and loopback HTTPS. Interactive installation collects the hostname before running
these checks, so invalid answers also stop before creating node state. `none`
enables intake, extraction, OCR, word search, direct source review and exports. `review` adds learned search and cited generated
answers; `transcription` adds recording transcription; `all` selects both AI
workflows. CPU evaluation does not require NVIDIA hardware.

Each checklist row reports what was observed, which task it enables, whether it
blocks installation, and a next action. Resolve every `BLOCK` and rerun the same
command. `NOTE` rows are capacity planning advice. Exit status is 0 when no
blocking prerequisite fails, 1 otherwise. An unsupported OS/architecture stops
before any runtime or storage probe. The Linux launcher currently targets x86-64;
this is its deployment contract, independent of the contributor's computer.

`--json` emits only one versioned document with `schema_version`, `ready`, and
`checks`. Every check has `name`, `state` (`pass`, `fail`, or `unknown`),
`observed`, `required_capability`, `blocking`, and `remedy`. An unknown blocking
check also prevents readiness. Consumers should use these fields, tolerate new
check names, and reject unsupported schema versions. JSON output excludes paths,
account names, device names and raw Docker/driver output.

For missing prerequisites:

- Install [Docker Engine](https://docs.docker.com/engine/install/) and the
  [Compose plugin](https://docs.docker.com/compose/install/linux/) for the host
  distribution. Arrange approved service-account engine access; Docker access is
  privileged. Never make its socket world-writable to pass a check.
- Have an administrator create only the dedicated node and matter-storage paths
  and assign them to the non-root service account. The account's primary group
  must also be non-root. Do not use a home directory, symlink, or shared export
  root. Existing selected directories must belong to that account. A first-install
  node root must be empty; use `--resume` only for the intended existing node.
- Leave more than the installer's 100 GiB storage safety reserve free on the
  selected filesystems. The larger profile targets above are advisory alpha
  planning figures, not validated minimums. Container-engine image storage may
  be on a different filesystem and needs separate capacity planning.
- Retain loopback HTTPS for evaluation, or supply a readable certificate/key
  pair trusted by the organization for explicit LAN access. Preflight checks the
  choice, server-name syntax and file access; it does not certify the pair's matching keys, identity,
  expiry or trust chain. Verify those before staff access.
- For AI tasks, install the NVIDIA driver and
  [Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
  The checklist checks registered Docker runtime support and the selected model
  plan against currently reported GPU capability and free memory. It also
  validates supported transcription languages and the diarization/profile combination.
  Unattended diarization staging also requires both `--accept-model-terms` and
  `--hf-token-stdin` before any installation writes. Preflight checks those
  choices without reading, validating or printing the token. It neither
  pulls a test image nor proves container/device or offline model readiness.

Directory writability is a metadata/access check with no write attempt; NAS
ACLs, quotas, read-only mounts and later capacity changes can still prevent
installation. A passing preflight is permission to attempt installation, not a
successful install or confidential-workload acceptance. The `doctor` and
synthetic acceptance steps below remain necessary.

## Interactive installation

```bash
./install
```

Run the installer as a dedicated, non-root service account. If `/srv` or a NAS
mount requires administrative setup, create the narrow node and storage paths,
assign them to that account, then run `./install` as the account. The installer
refuses to silently record UID/GID 0 for application containers.

The phases are deliberately explicit:

1. host and GPU preflight;
2. state/storage boundary creation;
3. allowlisted release-capsule hashing and staging;
4. authentication and TLS configuration;
5. versioned container build;
6. storage and administrator initialization;
7. pinned model staging and offline manifest sealing;
8. launch and health acceptance.

Use `--prepare-only` to build and configure without starting services. Use
`--dry-run --no-color` to inspect the exact command sequence without writes.
Dry-run prerequisite discovery is real and read-only: it rejects unsupported
hosts, missing runtime access, unsafe storage/TLS choices, and missing,
incompatible, undersized or currently occupied selected GPU hardware. Use
`preflight` to inspect prerequisites without going through configuration prompts.

## Unattended local-account example

Passwords and Hugging Face tokens are read only from standard input, never a
command argument. Because both are needed, use separate controlled staging
steps rather than concatenating secrets into a shell history. The interactive
installer is recommended for the initial release. Automation should invoke the
same commands from a secret manager and inspect exit codes.

## Model staging

The model vault uses exact revisions from `config/models.json`. It downloads to
the selected model root, hashes the transcription artifacts, writes the
offline approval manifest, and discards the token variable. Runtime AI
containers use offline flags and networks without external egress.

If a gated download fails, confirm the operator account accepted the model’s
terms, create a read-only Hugging Face token, and rerun preparation. Never put a
hub token in `.env`, Compose YAML, service environment, logs, or Git.

Transcription defaults to ungated ASR plus English alignment. Add Spanish with
`--transcription-languages en,es`. Add speaker clustering only with
`--enable-diarization --accept-model-terms`; the installer then requests a
one-time read-only hub token. Whisper translation uses the staged ASR artifact
and does not add a separate model download. A deployment that omits diarization
still produces transcripts and timestamps, with speaker separation explicitly
reported as unavailable.

## Acceptance

Run:

```bash
./install doctor --root /srv/recordbench
```

Then use only synthetic fixtures to verify login, matter creation, document
OCR, search, cited answers, video playback, transcription/diarization, exports,
matter closure, and cleanup. Validate GPU memory and concurrent workloads
outside RecordBench before allowing confidential material.

## Kerberos installations

Join the Linux host to the organization domain with SSSD first. Create an HTTP
service principal and keytab for the final RecordBench hostname, then supply the
keytab to the installer. The Kerberos Compose overlay mounts only the host NSS
socket and `nsswitch.conf` into the app so group lookup behaves like the joined
host; the authentication proxy receives the keytab and strips the browser’s
Negotiate token before forwarding an authenticated principal plus a shared
secret. Follow [Authentication](AUTHENTICATION.md) exactly.

## Upgrade

The installer stages an immutable, content-addressed release capsule under the
node root and gives every locally built image a release-specific tag. It does
not fetch or merge source code: review and update the clone first, then run:

```bash
./install update --root /srv/recordbench
```

An update requires a newly successful bundled encrypted backup unless no
bundled backup is configured and the operator supplies `--no-backup`. Operators
using their own backup method can use that flag after verifying their external
recovery copy against the [backup consistency requirements](STORAGE_AND_BACKUP.md).
It skips the bundled requirement; it does not validate an external backup or
ignore a configured bundled backup's failed/deferred receipt.
Resume and update validate the saved model profile, selected GPU devices,
generator memory reservation and transcription free-memory threshold against the
current hardware before running provisioning, backup or release commands. They
do not substitute an automatically chosen GPU or a smaller model to pass the
check. A completed offline resume or update does not require a new diarization
token; an unfinished resume that must stage models still checks its staging
options before continuing.

The new capsule is built without overwriting
the prior image set. If startup acceptance fails, configuration is returned to
the previous release and its images are relaunched. Old releases and images are
retained for deliberate operator cleanup; the updater never prunes them.


Storage preflight requires the nearest existing creation directory to belong to
the service account and deny group/other writes. Every parent must belong to
root or that service account and prevent replacement of its child. The service
account also needs read and search access to the existing creation directory and
every ancestor, matching the portable descriptor walk used during preparation.
Execute-only ancestors are rejected by preflight; select an accessible dedicated
path or arrange the required service-account access before retrying. A trusted
sticky system directory may contain an existing private service-owned directory;
it is never accepted as the creation directory itself. Root-owned protected
parents such as `/srv` are supported when the operator first creates the
service-owned directory beneath them. Non-sticky shared writable ancestors and
parents owned by another non-root account are refused before installation.
Installation creates each missing directory component with mode `0700`, even
when the caller's umask removes owner permissions. Directory creation runs in a
short-lived isolated child that inherits only the held parent directory
descriptor and sets its own umask; the installer never changes the calling
process's umask. It rechecks ownership and replacement protection
while walking held directory descriptors, refuses symbolic links, and applies
owner-only permissions to the selected node and storage directories without
changing existing ancestor modes. If those paths change after preflight,
preparation stops before following an unsafe replacement. Only newly created
protected directories may remain after such a failure; inspect them before
resuming.

Synthetic regression tests cover invalid server names stopping before state
creation, nested node and separate matter-storage paths under umasks `000`,
`0700` and `0777` as a non-root account, and
concurrent symlink, writable-directory and foreign-owner replacements. The
backup suite also round-trips synthetic control and managed SQLite stores from
these prepared nested directories into a clean restore target. That regression
uses simulated service/backup commands; an operator still needs the real encrypted
backup and isolated recovery acceptance in [Storage and backup](STORAGE_AND_BACKUP.md).
