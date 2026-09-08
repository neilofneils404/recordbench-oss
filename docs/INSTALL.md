# Installation playbook

For a source checkout used to write code and run tests, start with
[contributor setup](../CONTRIBUTING.md#set-up-a-development-checkout). The playbook
below installs an application node; `make bootstrap` prepares a development
environment and does not deploy the application.


For a complete local Apple Silicon evaluation, see [Standalone macOS](MACOS.md).
That experimental profile uses an ARM64 Linux VM and a native Metal generator;
the Linux/NVIDIA installer below does not manage Mac nodes.

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
Dry-run GPU discovery is real and read-only: it will reject missing,
incompatible, undersized, or currently occupied hardware rather than inventing
a successful topology.

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
The new capsule is built without overwriting
the prior image set. If startup acceptance fails, configuration is returned to
the previous release and its images are relaunched. Old releases and images are
retained for deliberate operator cleanup; the updater never prunes them.
