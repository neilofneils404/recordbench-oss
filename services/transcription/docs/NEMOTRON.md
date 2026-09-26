# Nemotron diarization integration

New installer configurations using `--enable-diarization` select
`nvidia/Nemotron-3-Diarization` at immutable revision
`0f087031414a6616bda8228f447d915a70a25720`. The model is ungated under
OpenMDW-1.1: no Hugging Face login, token, or gated-access approval is required.
Staging downloads the Transformers weights, two configuration files and model
card, excluding the separate NeMo checkpoint and demonstration media. The
stager records SHA-256 for every staged artifact. License obligations still
apply; ungated access is not a license exemption.

## Runtime boundary

WhisperX continues to handle source ASR, alignment and word assignment.
Nemotron runs in a separate interpreter built into the worker image. Its
Transformers source archive is pinned to commit
`002e1edf5b5198488297f401dd853056b6521d02` and SHA-256
`6ad0ee824d900cb9d884f57579d1ae49cf16f66c02b68a64dc713874d0a3464c`.
The model's [immutable upstream example](https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/0f087031414a6616bda8228f447d915a70a25720/README.md)
defines the native Transformers adapter. No remote model code is trusted.

`requirements-nemotron.lock` and `requirements-nemotron-build.lock` contain
hash-checked dependencies resolved for Linux x86-64/Python 3.11. They belong
only to `/opt/transcription/nemotron`, not the WhisperX interpreter. Resolve
updates deliberately with `uv pip compile --python-version 3.11
--python-platform x86_64-unknown-linux-gnu --generate-hashes --no-header
--no-annotate`, using the corresponding `.in` file and output `.lock` file.
Image-wide reproducibility and vulnerability acceptance require the remaining
release artifact gates; these locks alone do not establish them.

The worker verifies all manifest bytes before constructing an engine, then
requires the selected snapshot's three runtime files to match the verified
Nemotron artifact and exact revision. Keep the model cache read-only. The child
uses local files only and offline library settings; the worker's network policy
must independently deny egress. Private input paths travel over stdin rather
than process arguments. Dependency stderr is discarded and never becomes an
exported error. Output is size-limited and validated before speaker assignment.
Timeout and cancellation kill and reap the inference process group.

Float32 inference uses at most 25% of device memory through PyTorch's allocator
limit. That is not a reservation or a complete limit on CUDA allocations;
shared-device admission still requires the worker's VRAM checks and a scheduler.
The subprocess has a one-hour timeout. Longer media may fail this stage and
retain the source transcript; qualify duration/resource limits before support.

## Results and compatibility

The model produces up to eight anonymous speaker channels, including overlap.
Labels are not real-world identities. Minimum/maximum speaker hints are retained
in provenance but explicitly reported as unsupported. WhisperX assigns words
using overlap with `fill_nearest=False`; no overlapping turn is removed to
make the transcript exclusive. Silence returns no turns and is visibly degraded
when a usable transcript has no speaker attribution. Opting out never loads the
diarizer. Failure preserves aligned source text with a failed diarization stage.

Exports identify the selected model and revision. The pinned Transformers source
is build-declared provenance; it is not attestation of a separately modified
interpreter. Retain the release image digest with acceptance receipts.

Existing installations without a backend setting retain Community-1. New
configurations can select it explicitly with `--diarization-backend community-1`;
its gated access and separate notices still apply. Resume binds the saved
backend and staged receipt. Switching backends requires a reviewed configuration
and staging change, not merely rerunning resume with a different flag.

## Qualification boundary

Synthetic protocol tests cover malformed/nonfinite turns, eight-speaker bounds,
overlap, silence, offline environment, stderr/stdout contamination, size limits,
timeouts/cancellation, manifest tampering, opt-out and selected-model metadata.
They do not establish real audio quality or installed offline operation.

Before a supported release, freeze a rights-cleared synthetic gold corpus and
score real end-to-end ASR/alignment/diarization for WER, speaker-attributed WER,
DER, overlap and critical words. Include cold load and total job latency, not
only diarizer inference. Complete fresh installation, egress-denied execution,
recovery and resource acceptance on each advertised hardware profile. No
universal speedup or supported-release claim follows from the upstream benchmark.
