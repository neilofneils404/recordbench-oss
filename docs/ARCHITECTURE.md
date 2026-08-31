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

Documents pass through staged intake and ClamAV before extraction. Text PDFs
use native extraction; missing-text pages use bounded CPU OCR. Media enters a
durable transcription queue. The WhisperX worker performs transcription,
alignment, optional anonymous speaker clustering, and export generation; the
app projects transcript segments back into the matter index and generates an
automatic source summary.

Model workers have no published ports and run on an internal Docker network.
The transcription worker has no network namespace at runtime. The app may need
egress only for a configured OIDC provider. Companion-service URLs require an
exact operator allowlist.

Matter storage is configurable and may be a dedicated host-mounted NAS path.
RecordBench remains a temporary review workspace: exports leave the system,
matters can be closed and purged, and the independent Transcript Studio queue
has a short expiry.
