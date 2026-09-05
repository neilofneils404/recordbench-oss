# Changelog

## Unreleased

- 2026-09-05: Complete matter bundles now include every saved draft and final
  Report as editable Markdown and Word with a manifest inventory, including
  empty Reports and collision-safe filenames. A bounded database snapshot
  preserves edits and section order during concurrent writes. Existing exact
  source validation applies; inconsistent, unresolved, or oversized Report
  work returns no complete bundle. Interrupted-close recovery can export
  uncited Reports without opening quarantined sources; cited Reports require
  restored source access. No persistent schema or close-authority change.
- Keep bundled backups consistent after application restart: freeze managed
  registries and WAL-backed control databases independently, and capture the
  PostgreSQL projection inside the same stopped application boundary. Restore
  now verifies managed SQLite stores and recorded inventory as well as control
  stores. Synthetic mutation, failure/recovery and optional encrypted
  repository/PostgreSQL import tests cover the boundary. Operators retain the
  choice of an external backup system or the optional bundled method with a
  host-accessible destination.
- Versioned the stacked-record favicon and application-mark URLs so browsers
  cannot retain the superseded monogram after an upgrade.
- Added the first staff-visible Slice 1A increment: loose-file selection now
  receives a matter-scoped metadata preview before byte transfer, accounts for
  every selected row, distinguishes ready, scanner-blocked, unsupported,
  repeated-path, oversized, and invalid entries, and requires explicit staff
  confirmation before the ready subset enters the retained resumable upload
  path. The UI keeps ineligible rows visible, preserves retry/reselection and
  the direct no-JavaScript fallback, and labels detected type, readability,
  source version, content duplicates, and scans as pending or not run rather
  than inventing results. Synthetic API, isolation, retained-upload, desktop,
  mobile, keyboard, focus, and no-overflow acceptance pass locally. This is an
  OSS review candidate, not deployed; byte-derived preflight, durable caching,
  and content/near-duplicate analysis remain deferred.
- Recovered an interrupted Review Map refresh as a visible, retryable failure
  on application restart so abandoned analysis state cannot block safe matter
  closure indefinitely; completed work and prior review decisions stay intact.
- Honored explicit source-kind exclusions in Review questions before retrieval
  backfill, evidence budgeting, prompting, and generation, while keeping
  narrative negation and inclusive “not only … but also” wording intact.
- Serialized focused-answer and broader-investigation admission in each Review
  conversation, including retries, so concurrent requests cannot both enter the
  same thread or append work out of order.
- Preserved cited investigation exports after a deletion attempt freezes source
  storage, without reopening quarantine or recreating a live source tree, and
  made final bundles fail explicitly instead of silently omitting investigation
  or every-source-check ledgers beyond their bounded export limit.
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
