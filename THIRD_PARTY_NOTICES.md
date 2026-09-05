# Third-party notices

This is a prerelease inventory, not a substitute for the license texts shipped
by upstream projects. Public release remains blocked until an organization-approved
software-composition and model-license review confirms this record.

## Runtime foundations

RecordBench builds on Python, FastAPI/Starlette, Uvicorn, PostgreSQL, pgvector,
nginx, ClamAV, Tesseract, Poppler, FFmpeg, ImageMagick, Apache HTTP Server,
`mod_auth_gssapi`, restic, vLLM, PyTorch, Transformers, sentence-transformers,
WhisperX, faster-whisper, pyannote.audio, and their transitive dependencies.
Container and Python package metadata retain the authoritative upstream license
and notice material. Operators must review the resolved image and package lock
inventory for the release they deploy.

## Recording-check dependency

The recording check pins `webrtcvad-wheels` 2.0.14. The Python wrapper uses the
MIT license; the bundled WebRTC implementation has its own BSD notice. Retain
the [upstream license texts](https://github.com/roman-nekrasov/py-webrtcvad-wheels/blob/master/LICENSE)
shipped with the dependency. This CPU VAD adds no downloaded model weights or
network service.

## Default model artifacts

The immutable IDs and revisions are recorded in `config/models.json`. The
current declarations are:

- Qwen3.5 4B, Qwen3.5 9B, Granite Embedding English R2, and GTE ModernBERT reranker:
  Apache-2.0 as declared upstream;
- faster-whisper large-v3: MIT as declared upstream;
- torchaudio English and Spanish alignment artifacts: BSD-2-Clause as declared
  upstream;
- pyannote Community-1 diarization: CC-BY-4.0 and gated upstream terms;
- Community-1 dependency artifacts: publication-blocking upstream-terms review
  is still required.

No model weights are committed to this repository. The installer retrieves
exact revisions only after the operator reviews applicable terms. A Hugging
Face token is used for staging and is not retained by runtime services.
