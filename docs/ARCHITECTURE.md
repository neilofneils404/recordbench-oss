# Architecture

```text
staff browser
    │ HTTPS
    ▼
gateway ── optional Kerberos proxy
    │
    ▼
RecordBench app ── PostgreSQL + pgvector (derived retrieval index)
    │            ├─ ClamAV (stream scan)
    │            ├─ embedding + reranker worker (offline GPU)
    │            ├─ vLLM generator (offline GPU)
    │            └─ transcription API → durable ephemeral queue
    │                                      │
    │                                      ▼
    │                               WhisperX worker
    ▼
managed matter storage + SQLite control record
```

The app, not the model, owns authorization, matter isolation, audit attribution,
citations, exports, and deletion. PostgreSQL is a rebuildable projection of
matter source units. Candidate retrieval combines lexical and vector lanes,
then a cross-encoder reranks a bounded set. The generator sees only the selected
evidence; a separate deterministic verifier checks claims and citations.

Loose-file selection first uses a matter-authorized, CSRF-protected metadata
preflight. It returns one content-minimized row per selected file without
copying bytes, reserving capacity, or creating an upload session; filename
type is explicitly provisional, while detected type, readability, source
version, content duplicates, and scan results remain pending. Explicit staff
confirmation sends only the eligible subset through the retained upload route,
which revalidates metadata and remains authoritative for staging, signature
checks, configured ClamAV policy, and failure recovery.

Accepted documents then enter extraction. Text PDFs use native extraction;
missing-text pages use bounded CPU OCR. Media enters the durable media queue,
which performs a bounded offline recording check before processor submission.
An existing cancelled queue state plus source/version-bound inspection metadata
holds playback-only or review-needed recordings without claiming transcript
success; see [recording-check contracts](MEDIA_PREFLIGHT.md). The WhisperX worker performs transcription, alignment, optional
anonymous speaker clustering, and export generation; the app projects
transcript segments back into the matter index and generates an automatic
source summary.

Model workers have no published ports and run on an internal Docker network.
The transcription worker has no network namespace at runtime. The app may need
egress only for a configured OIDC provider. Companion-service URLs require an
exact operator allowlist.

Matter storage is configurable and may be a dedicated host-mounted NAS path.
RecordBench remains a temporary review workspace: exports leave the system,
matters can be closed and purged, and the independent Transcript Studio queue
has a short expiry.
