# Changelog

## Unreleased

- Established RecordBench OSS as the upstream source for portable product
  behavior, with synthetic clean-room reproduction rules for defects found by
  private downstream deployments.
- Added a contribution and pull-request contract covering user outcomes,
  validation evidence, security/lifecycle impact, immutable releases, and the
  strict separation of private deployment overlays.

## 0.1.0-alpha.2 — private review candidate

- Imported the RecordBench 0.1 application into a fresh, sanitized history.
- Added environment-neutral storage, service endpoint, model, and identity
  configuration.
- Bundled the WhisperX transcription and diarization subsystem.
- Added isolated Compose profiles and the RecordBench node provisioner.
- Added production-capable Argon2id local accounts alongside OIDC and Kerberos.
- Generalized identity, fixtures, and transcription documentation for an
  environment-neutral release candidate.
- Added adaptive one-to-many NVIDIA GPU placement, portable and quality
  generator tiers, CPU retrieval fallback, explicit tensor-parallel overrides,
  and fail-closed VRAM/compute-capability preflight.
- Split ASR, language alignment, and gated diarization into independently
  selected model modules.
- Hardened publication scanning across filenames, archives, media metadata,
  certificate/key formats, generic secret shapes, and Git identity/ref history.
- Corrected hosted-CI system dependencies and test-only storage admission, and
  removed unsupported model-quality and throughput claims from the UI.

This build is not cleared for public release until the publication checklist
and licensing review are complete.
