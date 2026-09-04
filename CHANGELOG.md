# Changelog

## Unreleased

- Kept every-source review honest when a source-scoped search returns no
  passage: the source now remains **Needs attention** with direct-review or
  criterion-refinement recovery instead of being automatically labeled **Not
  identified**, while source-change provenance still supersedes the search
  miss.
- Replaced the media review page's long, nested tool column with persistent
  Playback, Summary, Export, and Clips tabs, keeping every recording tool one
  click away without moving the transcript or scrolling to its end.
- Restored grounded answers when PostgreSQL retrieval includes transcript
  evidence by canonicalizing citation modality before source-version checks;
  made Sources open directly into a compact, 100-row browse view with inline
  type filtering and upload as a separate action; and made media metadata,
  speaker review, transcript controls, and scrollbars independently scrollable
  and theme-consistent.
- Established RecordBench OSS as the upstream source for portable product
  behavior, with synthetic clean-room reproduction rules for defects found by
  private downstream deployments.
- Added a contribution and pull-request contract covering user outcomes,
  validation evidence, security/lifecycle impact, immutable releases, and the
  strict separation of private deployment overlays.
- Added discoverable matter management and per-matter settings, with guarded
  owner-or-administrator closure, explicit cross-owner administrator warnings,
  final export access, active-work refusal, and attributed deletion audit.
- Moved transcript speaker correction into a directly reachable, context-preserving
  review panel with explicit human confirmation, and added actionable bounded
  recovery details when an optional transcript overview fails.
- Improved grounded review quality for exact-record questions, explicit
  written-and-spoken requests, and broad matter orientation: precise machine
  records can be rescued after reranking, evidence-kind wording is independently
  checked, partial modality results are disclosed, and broad summaries use
  source-diverse facets while suppressing disclaimer-only passages.
- Unified focused answers and broader investigations in one durable Review
  conversation, with cited investigation results available for follow-up, and
  presented collection-wide screening as the plain-language **Check every
  source** task with truthful time and coverage differences.
- Added a bounded, fail-soft sampled-frame OCR contract with exact decoder
  timestamp/frame provenance and hard resource limits. The capability remains
  explicitly non-searchable until matter-scoped persistence, citation, export,
  purge, and browser acceptance are implemented.

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
