# CPU execution and validation

The experimental Apple Silicon deployment runs this service in an ARM64 Linux
container on the same Mac. Select the `worker-cpu` Dockerfile target and set
`TRANSCRIPTION_V2_DEVICE=cpu` for both the API readiness process and worker.
The ordinary `worker` target and default `cuda` device retain the Linux GPU
deployment behavior. MPS is not an accepted device for this WhisperX backend.

From the repository root, the CPU image can be built with:

```sh
docker build --platform linux/arm64 --target worker-cpu \
  -t recordbench/transcription-worker:cpu services/transcription
```

The CPU target installs Torch 2.8.0, torchaudio 2.8.0, and torchvision 0.23.0
from the official CPU wheel index before installing the existing `ml` extra.
It fails the build if Torch contains a CUDA runtime. Keep the worker's
`network_mode: none`, private writable data volume, read-only model volume,
non-root identity, and normal resource limits in the deployment configuration.
CPU execution does not replace the container isolation boundary.

The CPU image pins pyannote.audio 4.0.7 and deliberately excludes TorchCodec:
the Torch 2.8-compatible codec has no Linux ARM64 wheel. WhisperX decodes with
FFmpeg and passes preloaded waveforms to pyannote, which supports that path
without the optional decoder. A build-time check imports the real libraries,
decodes synthetic audio, and verifies waveform reads, duration, and cropping.
It does not load model weights or evaluate recognition quality. Do not use
pyannote's direct file-decoding API in this image; it requires TorchCodec.

## Runtime contract

Required configuration is unchanged except for explicit CPU selection:

- `TRANSCRIPTION_V2_PIPELINE=whisperx`
- `TRANSCRIPTION_V2_DEVICE=cpu`
- `TRANSCRIPTION_V2_CPU_COMPUTE_TYPE=int8` (the CPU default; `float32` is an
  explicit alternative requiring a substantially larger memory budget)
- `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`
- `TRANSCRIPTION_V2_DATA_ROOT`, `TRANSCRIPTION_V2_DATABASE`,
  `TRANSCRIPTION_V2_MODEL_CACHE`, and `TRANSCRIPTION_V2_MODEL_MANIFEST` pointing
  to the deployment's mounted state and approved model cache
- the existing private API token file and bounded disk/upload/retention settings

Use the deployment's existing pinned model staging process and run
`transcription-v2 verify-models` before `transcription-v2 worker`. Model IDs,
exact revisions, licenses, and artifact hashes remain controlled by the root
model configuration and manifest. CPU mode cannot bypass that manifest gate.
The worker passes the manifest's exact verified ASR snapshot path to WhisperX;
it does not depend on a cached floating `main` revision. Every snapshot file
must still match the approved artifact's file identity before loading.
`transcription-v2 check` requires offline flags, packaged VAD, ffmpeg/ffprobe,
available disk, and a present manifest, but does not query NVIDIA hardware.
The worker serializes CPU runs with a lock under its data root. Use one worker
per instance; memory admission remains the container's responsibility.

If optional Community-1 artifacts have not been staged, retain the explicit
`TRANSCRIPTION_V2_ALLOW_DEGRADED_DIARIZATION=1` setting. The service reports
speaker separation as unavailable. CPU mode does not silently relax that gate.

Each CPU job uses the selected profile's existing models and decoding search,
with `int8` ASR execution and batch size 1. The exported profile records these
effective values. GPU profile constants remain unchanged. CPU throughput,
memory requirements, and output equivalence have not been established by the
synthetic unit suite; complete representative transcription, alignment,
translation, optional diarization, restart, export, and deletion evaluation on
the exact staged models before treating this configuration as validated.

The same staged artifact is quantized by CTranslate2 at load time for CPU int8
execution; no alternate model repository or checkpoint is selected. The
float32 override keeps greater precision but large-v3 weights alone require
roughly 6 GB before working memory and alignment, so a 4 GB container cannot
accommodate that override. Record precision alongside every quality evaluation.

## Observed synthetic acceptance

An Apple Silicon evaluation on 2026-09-08 used an ARM64 Linux VM, four assigned
CPU cores, WhisperX 3.8.6, the approved large-v3 ASR and English alignment
artifacts, CPU int8 execution, and batch size 1. The worker ran with Docker
networking disabled, a read-only root filesystem and model volume, and a
non-root user.

A 6.335-second synthetic recording produced the expected three sentences,
three transcript segments, and 16 aligned words. After normalizing the spoken
number "nine" and output "9", the transcript matched exactly. The second
successful run took 21.883 seconds from queue processing through export;
that interval included model initialization but excluded manifest verification.
TXT, JSON, CSV, SRT, VTT, DOCX, and manifest files were present in a ZIP that
passed integrity checking. Deleting the job removed its file tree and rows.

A 4 GiB container was killed by the memory limit during model initialization.
Two runs completed at 5 GiB, but the recorded cgroup memory peak reached that
limit. These measurements justify additional headroom; they do not establish
a minimum for longer recordings or concurrent workloads. The initial runs used
the worker image with updated application source mounted for integration
testing.

The final immutable worker image subsequently passed the same test without a
source override in a 12 GiB VM, with a 6 GiB worker limit. Processing took
21.029 seconds, all 16 words aligned, and the normalized transcript again
matched exactly. Exported JSON contained the verified model revisions,
licenses, and manifest hash; export integrity and job deletion passed. The
process peak resident memory was approximately 5.05 GiB, and the cgroup peak
reached its 6 GiB limit. The container exited successfully without an OOM kill.
This successful short run does not establish memory headroom for longer audio.

This is one clean synthetic speech sample, not a representative accuracy
evaluation. Noise, overlapping voices, multiple languages, translation,
diarization, long recordings, cancellation, and concurrent workloads remain
separate acceptance work.

## Developer checks

An isolated Python 3.12 environment can install the service and ML dependencies
on native Apple Silicon for dependency and unit checks:

```sh
uv venv .venv-transcription --python 3.12
uv pip install --python .venv-transcription/bin/python \
  --excludes services/transcription/requirements-cpu-excludes.txt \
  -e 'services/transcription[ml,dev]' 'pyannote.audio==4.0.7'
.venv-transcription/bin/python -m pytest services/transcription/tests
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYANNOTE_METRICS_ENABLED=0 \
  .venv-transcription/bin/python services/transcription/scripts/check-cpu-runtime.py
```

This does not stage models or start an exposed service. The runtime check also
requires `ffmpeg` on PATH. The deployment uses the Linux container's package.

Primary upstream references:

- [WhisperX CPU usage](https://github.com/m-bain/whisperX#usage--command-line)
- [CTranslate2 hardware support](https://opennmt.net/CTranslate2/hardware_support.html)
- [CTranslate2 compute types](https://opennmt.net/CTranslate2/quantization.html)
- [PyTorch 2.8 CPU installation](https://pytorch.org/get-started/previous-versions/#v280)
- [pyannote 4.0.7 waveform IO](https://github.com/pyannote/pyannote-audio/blob/4.0.7/src/pyannote/audio/core/io.py)
