# RecordBench Transcription Service

This bundled service provides RecordBench's durable media queue, WhisperX
transcription, forced alignment, optional Nemotron or Community-1 speaker diarization,
review exports, and short-lived delivery lifecycle. It can also run the
optional Transcript Studio UI.

The API, worker, and cleanup path are bundled into the private Compose mesh.
Transcript Studio is not published by the default deployment; an operator who
enables it must place it behind the same trusted authentication boundary.

Real inference is deliberately offline. Model terms are accepted and pinned
artifacts are staged with the root installer before the worker starts. The
Hugging Face token is never placed in the runtime environment.

See the root installation guide and [model policy](../../docs/MODELS.md).

Nemotron setup, offline behavior and qualification limits are described in
[the integration guide](docs/NEMOTRON.md). New installer configurations select
ungated Nemotron when diarization is enabled; existing configurations retain
their saved backend.

## Reproducible dependencies

The API/UI and isolated Nemotron interpreter use hash-locked Python environments.
Nemotron uses Torch 2.14.0 with CUDA 12.6; the WhisperX worker retains its separate
dependency contract. See [dependency locks](../../docs/DEPENDENCIES.md) for
regeneration, verified tokenizer staging, and remaining release qualification.

Installed workers load ASR from the exact manifest-approved snapshot directory,
without relying on a mutable Hugging Face `main` cache reference. Missing or
changed snapshots fail before model loading. The Fast profile needs its own
approved Turbo artifact; the default catalog currently stages large-v3 only.
It must not silently substitute a model or download one during a job.

## Profile and language admission

The API verifies the approved model manifest once at startup without importing
ML libraries or running inference. `/v1/profiles` reports ASR availability,
English-translation availability, and locally approved alignment languages.
These describe model inventory, not GPU capacity or whole-worker readiness.
An unavailable profile or language is rejected before durable upload ingestion
and job creation. The HTTP multipart parser may already have spooled the request;
this is not a promise to reject before receiving request bytes.

Transcript Studio obtains its choices from that API. Optional
`TRANSCRIPTION_V2_PROFILE_NAMES` and `TRANSCRIPTION_V2_LANGUAGE_CODES` settings
can restrict the choices, but cannot enable an unstaged option. An empty or
unavailable inventory does not invent a fallback choice. Missing setup leaves
health/status available while refusing new work. After staging or changing
approved models, restart the API and worker through the deployment procedure to
verify the new inventory. Per-request checks compare verified file identities;
they do not repeatedly hash multi-gigabyte checkpoints.

Installed workers bind English and Spanish alignment to the approved torchaudio
checkpoints before importing a model loader. Unsupported auto-detected languages,
missing/changed checkpoints and explicit unapproved overrides fail alignment
without a model-download fallback. Standalone caller-managed adapters keep their
existing behavior when no approved readiness object is supplied. The existing
stage-result contract preserves source transcription when alignment fails;
this does not qualify the unsupported language.

Fast requires a separately staged Turbo snapshot. Translating a Fast result
additionally requires the approved large-v3 snapshot. No profile silently
substitutes a model, and no API/UI availability result replaces worker checks.

## Operator-selected models

The reference profiles are a tested-configuration target, not a universal model
loader. See [model choice and compatibility](../../docs/MODEL_CONFIGURATION.md)
for current ASR/alignment restrictions, upstream acquisition terms, and the
planned administrator model configuration/import boundary.
