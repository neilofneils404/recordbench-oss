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
confirmation records the complete selection in the control database before
sending only the eligible subset through the retained upload route,
which revalidates metadata and remains authoritative for staging, signature
checks, configured ClamAV policy, and failure recovery. [Selection receipts](INTAKE_RECEIPTS.md)
retain explicitly browser-reported selection reasons separately from server
filename checks, byte receipt and source availability,
use idempotent metadata/session bindings and exact source versions, and provide
coherent paginated views and complete exports. Their tables stay in the existing
temporary-matter deletion and backup boundary. Atomic matter/creator/workspace
receipt, selected-row and metadata-byte limits admit writes before storage grows;
only owners can cancel empty pending uploads and discard their receipts. Received
source data and saved partial bytes prevent discard.
Each new resumable upload item identifies a separate [received occurrence](UPLOAD_OCCURRENCES.md),
even with repeated paths or bytes. The existing source-registry key retains
same-item retry identity across finalization and restart, including copy fallback.

[Source folder navigation](SOURCE_FOLDER_NAVIGATION.md) uses the existing
matter-scoped source catalog and organization joins. A literal separator-bound
relative-path prefix restricts source rows; bounded SQL grouping pages immediate
children and descendant counts under the same filters. It adds no stored state
and preserves exact source links and existing source-set memberships.

[Identical-byte comparison](EXACT_BYTE_MATCHES.md) uses a derived digest/size
lookup updated transactionally with source catalog projections. It joins the
current admitted source version and size, and normal registry reconciliation
rebuilds it. The existing catalog row and registry JSON shapes stay compatible
with previous readers. SQL materializes at most 100 display rows and aggregates
the matter's current digest/size groups once before joining their counts. Indexed
source identities avoid scanning the byte-row intermediate for every display row;
folder and matching-only filters stay database-native.
Comparison URLs use existing matter-bound source action tokens, never hashes.

[Email extraction](EMAIL_ATTACHMENT_COVERAGE.md) traverses the parent body tree
without entering attached messages or multipart attachments. All non-report
`message/*` children are boundaries even without filenames or attachment disposition. Header sections
inventory attachment names/types and state that attachment contents were not
processed or searched. All parsed parts still count toward the MIME limit,
including descendants of attachment boundaries; malformed MIME containers fail
with ordinary retry/remove recovery. The existing catalog supplies a
matter-scoped email count for readiness and query-time coverage without reading
source files. Email does not block otherwise-ready queries, but `partial_query`
also identifies incomplete attachment coverage with zero excluded source files.
The ordinary answer coverage snapshot flows into UI and work-product exports.
Investigation results combine source/attachment coverage with the focused-search
caution, retaining both in standalone and complete-bundle exports. Structured
delivery/read-receipt body parts are not invented attachment entries; explicit
attachment disposition or filenames still identify real attached report data.
Related MIME containers select their body root and inventory other resources;
missing/ambiguous root references fail rather than choosing another text part.
Coverage links use the complete source list in server and live browser rendering,
so combined processing/email coverage can reach both affected and ready sources.
No schema or source registry shape changes; older passages and indexes are not
silently rewritten or assigned a new citation basis.

Accepted documents then enter extraction. Text PDFs use native extraction;
missing-text pages use bounded CPU OCR. Media enters the durable media queue,
which performs a bounded offline recording check before processor submission.
An existing cancelled queue state plus source/version-bound inspection metadata
holds playback-only or review-needed recordings without claiming transcript
success; see [recording-check contracts](MEDIA_PREFLIGHT.md). The WhisperX worker performs transcription, alignment, optional
anonymous speaker clustering, and export generation; the app projects
transcript segments back into the matter index and generates an automatic
source summary.

An extracted document can be marked ready before indexing and registered-source
staging cleanup finish. Matter search readiness therefore uses the durable job
state as well as the source catalog. Integration tests must wait for that same
matter readiness before expecting search results, while retaining source and
result assertions. A paused-cleanup regression proves that extraction alone
does not permit matter search or closure, and that search becomes available
after the job finishes. This contract does not delay ordinary source viewing.

Model workers have no published ports and run on an internal Docker network.
The transcription worker has no network namespace at runtime. The app may need
egress only for a configured OIDC provider. Companion-service URLs require an
exact operator allowlist.

Matter storage is configurable and may be a dedicated host-mounted NAS path.
RecordBench remains a temporary review workspace: exports leave the system,
matters can be closed and purged, and the independent Transcript Studio queue
has a short expiry.
