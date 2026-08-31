# Installation playbook

## Supported shape

RecordBench targets a modern x86-64 Linux host with Docker Engine, Docker
Compose v2, 64 GB RAM minimum, and ample temporary and matter storage. The
bundled CUDA/vLLM profile requires NVIDIA compute capability 7.5 or newer. The
installer exposes four explicit capability profiles:

| CLI value | Intended use | Minimum GPU topology |
| --- | --- | --- |
| `none` | CPU evaluation: intake, extraction, lexical search, manual review, and exports | none |
| `review` | learned retrieval, reranking, and cited local generation | one NVIDIA GPU |
| `transcription` | media transcription without the review-model services | one NVIDIA GPU |
| `all` | review plus transcription, co-resident or separated by capacity | one supported NVIDIA GPU |

The current conservative floor is 16,000 MiB total VRAM for a single-device
portable review lane and 20,000 MiB for a single-device full lane, plus the free
VRAM headroom enforced during preflight. These are admission bounds, not proof
of acceptable latency or quality on every card.

Plain `./install` defaults to `none`; an operator must deliberately select a GPU
profile. Automatic topology co-locates conservatively sized services on a
one-GPU node, separates generation and transcription when a second device
exists, and can place retrieval on a third. Four, six, or eight visible devices
do not change the workflow or prevent installation: the planner assigns the
highest currently usable compatible cards to the service lanes it needs and
leaves the rest available. If the preferred quality/separated plan does not
fit, automatic mode tries a packed plan and the portable tier before failing.
Explicit GPU indices and a tensor-parallel generator set let an operator use a
larger host deliberately.

Model preflight selects the pinned portable or quality tier from VRAM and
sharing pressure. A second GPU is an optional throughput optimization, not an
installation requirement. RecordBench does not yet pause one service to lend
its memory to another; a shared device uses co-resident services with explicit
memory and concurrency limits. Do not treat any mapping as a universal capacity
claim: representative acceptance on the exact GPU model, VRAM, drivers,
collection size, and concurrency remains required before staff use.

Use `--gpu-layout shared|split`, `--generator-gpus`,
`--transcription-gpu`, `--retrieval-device`, and `--retrieval-gpu` only when
overriding automatic topology. `--review-model-profile portable|quality`
selects a pinned tier; incompatible, undersized, or currently oversubscribed
GPU plans fail before node state is created.

The preferred automatic full-profile mapping, when capacity is available, is:

| Compatible visible GPUs | Generator | Transcription | Retrieval |
| --- | --- | --- | --- |
| 1 | highest-capacity card, portable tier | same card | CPU |
| 2 | highest-capacity card | next card | CPU |
| 3 or more | highest-capacity card | next card | third card |

Additional devices are intentionally not consumed just because they exist.
Horizontal replicas and job routing require a separately tested deployment
overlay; tensor parallelism is available only through an explicit generator
GPU list. This makes an eight-GPU server valid without pretending that the
alpha automatically scales linearly across eight cards.

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

An update requires a newly successful encrypted backup unless the operator
explicitly supplies `--no-backup`. The new capsule is built without overwriting
the prior image set. If startup acceptance fails, configuration is returned to
the previous release and its images are relaunched. Old releases and images are
retained for deliberate operator cleanup; the updater never prunes them.
