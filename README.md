<p align="center">
  <img src="src/case_intelligence/static/favicon.svg" width="104" alt="RecordBench logo">
</p>

<h1 align="center">RecordBench</h1>

<p align="center"><strong>Review sensitive records while keeping the sources in view.</strong></p>

RecordBench is a self-hosted workspace for legal and investigation teams. It
brings documents, images, email, spreadsheets, audio, and video into one
temporary matter workspace where a team can search, review, ask questions,
organize findings, and export its work.

RecordBench is designed to run on infrastructure you control. Source material
and local AI requests do not need to be sent to a commercial cloud service.

> **Alpha software:** RecordBench is a prerelease project. It is not yet a
> self-service production release. Test it with synthetic material and validate
> installation, security, backup, restore, and model behavior before using
> confidential records.

## What you can do

- Create private matters with individual membership, administrator oversight,
  session identity, and attributed audit history.
- Upload individual files or a folder containing PDFs, Word documents, text,
  email, spreadsheets, images, audio, and video.
- Scan every upload with ClamAV before it enters a matter.
- Extract existing text and apply OCR to scanned pages and images.
- Transcribe audio and video, optionally separate speakers, follow the
  transcript during playback, and open cited moments at the relevant time.
- Review the record in one saved conversation: ask a focused question,
  investigate more deeply, and refine the cited result without starting over.
- Check every source against a defined criterion as a specialized task while
  preserving the frozen population, coverage, and human-review status.
- Keep conversations, notes, people, places, dates, reports, and other work
  product organized inside the matter.
- Export answers, conversations, transcripts, summaries, clips, notebooks,
  reports, and complete matter work product.
- Manage temporary matters from one place. Matter owners and RecordBench
  administrators can export, then deliberately close and delete a matter when
  the work is finished.

## Review without choosing a processing mode

| Task | Use it when you need to… |
| --- | --- |
| **Review** | Ask a focused question, investigate through several searches, and continue with follow-ups in one cited conversation. The composer explains the time and coverage difference. |
| **Check every source** | Apply the same criterion to every source in a frozen collection and validate the results. This is a specialized source-screening task, not another chat type. |
| **Review Sources** | Browse up to 100 sources immediately, filter by type or collection, open filenames directly, upload separately, play media, and work with a transcript while its metadata remains independently scrollable. |

Focused answers and broader investigations share conversational continuity;
the processing strategy stays behind task language. Checking every source stays
separate because it freezes a population and produces one decision per source.

## How it works

1. **Intake:** RecordBench copies an upload into a private staging area and
   scans it for malware.
2. **Processing:** It extracts usable text, applies bounded OCR where needed,
   and sends selected media through the bundled transcription queue.
3. **Indexing:** It divides the resulting text into traceable passages and
   makes them available to word and meaning-based search.
4. **Evidence selection:** A multi-stage retrieval pipeline finds candidate
   passages, combines keyword and semantic results, and reranks the candidates
   for the question being asked.
5. **Answering:** A local generation model answers from the selected material.
   RecordBench checks source support, shows citations and collection coverage,
   and reports important limitations instead of hiding them.
6. **Human work product:** The reviewer can inspect the source, save useful
   material, export it, or correct machine-generated transcript labels before
   anything is treated as finished work.

A failed source remains visible and is excluded from searching until repaired;
it does not prevent the rest of the matter from being used.

## What RecordBench uses

These are the current bundled defaults. Exact model revisions and license
information live in [`config/models.json`](config/models.json).

| Component | What it does in RecordBench |
| --- | --- |
| **Python, FastAPI, Jinja, and JavaScript** | Run the multi-user web application, background work, and review interface. |
| **PostgreSQL, pgvector, and SQLite** | Store matter control data, full-text indexes, semantic vectors, queues, sessions, and audit history. |
| **ClamAV** | Scans uploads before they can become reviewable matter sources. |
| **Tesseract and Poppler** | Render and OCR scanned PDF pages and image evidence. |
| **Granite Embedding English R2** | Converts passages and questions into vectors for meaning-based retrieval. |
| **GTE ModernBERT reranker** | Reorders candidate passages so the strongest evidence reaches the answering model. |
| **Qwen3.5 4B or 9B through vLLM** | Generates local source-grounded answers, summaries, and review assistance. |
| **WhisperX and faster-whisper large-v3** | Transcribe media and align transcript text to timestamps. |
| **Optional pyannote diarization** | Separates anonymous speaker clusters when its separately gated models are enabled. |
| **FFmpeg** | Probes media, prepares browser-compatible playback, and creates requested clips. |
| **nginx, local accounts, OIDC, or Kerberos** | Provide HTTPS and selectable identity options for different organizations. |
| **Docker Compose and restic** | Package the services and provide encrypted backup and restore tooling. |

Models are run locally after a one-time staging step. Runtime model containers
are configured for offline operation. Diarization is optional because its
upstream model terms require separate acceptance.

## Minimum recommended hardware

These are straightforward starting recommendations for the alpha. They are not
collection-size or concurrency guarantees; larger matters, longer recordings,
and more simultaneous users need additional storage and capacity.

| Intended use | CPU | RAM | NVIDIA GPU | Free SSD before matter data |
| --- | ---: | ---: | --- | ---: |
| **CPU evaluation** — intake, OCR, word search, source review, and exports | 8 cores | 16 GB | None | 150 GB |
| **Local document review** — evaluation features plus semantic retrieval, reranking, and local answers | 12 cores | 32 GB | 1 GPU with 16 GB VRAM | 200 GB |
| **Every-source checks and media** — document review plus transcription and optional diarization | 16 cores | 64 GB | 1 GPU with 24 GB VRAM | 300 GB |

Use a modern x86-64 Linux host with Docker Engine and Docker Compose v2. GPU
profiles require an NVIDIA card with compute capability 7.5 or newer and the
NVIDIA Container Toolkit. One suitable GPU is enough to begin; additional GPUs
can separate generation, transcription, and retrieval work. They improve
capacity but do not change the available workflows.

Matter storage may be a dedicated local path or a host-mounted NAS path. The
free-space figures above still need room for container images, model files,
temporary processing, and the configured safety reserve. Collection storage is
additional and depends on what the organization intends to review.

## What RecordBench is not

RecordBench is not:

- the authoritative evidence warehouse or a legal-hold system;
- a case-management or filing system;
- a validated redaction platform;
- a guarantee that OCR, transcription, retrieval, or generation is complete
  or correct; or
- a substitute for a lawyer, investigator, analyst, or other human reviewer.

Transcripts describe what the machine heard, not independently established
facts. Generated answers are review aids and should always be checked against
their cited sources.

## Quick start

The lowest-barrier path is the CPU evaluation profile on a Linux host with
Docker Compose:

```bash
git clone https://github.com/neilofneils404/recordbench-oss.git recordbench
cd recordbench
./install --help
./install
```

The installer defaults to CPU evaluation, loopback-only HTTPS, and local
accounts. NVIDIA Container Toolkit is required only when selecting a GPU
profile. Read the complete [installation playbook](docs/INSTALL.md) before an
installation intended for staff access.

The installer also provides commands for node diagnostics, encrypted backup,
isolated restore testing, and versioned updates:

```bash
./install doctor --root /srv/recordbench
./install backup --root /srv/recordbench --repository /mnt/backup/recordbench \
  --recovery-key-output /mnt/recovery/recordbench-password
./install restore --root /srv/recordbench \
  --restore-target /srv/recordbench-restore-test
./install update --root /srv/recordbench
```

## Data and repository boundaries

RecordBench is a temporary review workspace. Matter bytes live under the
operator-selected managed storage path. Closing a matter can permanently
remove that workspace, so users should export anything they need to retain.
Deletion refuses active work, requires the exact matter name plus a permanent
deletion acknowledgement, preserves originals outside RecordBench, and leaves
only content-minimized attributed audit and closure records.

No case data, organization secrets, internal accounts, private deployment
coordinates, certificates, or credentials belong in this repository.

## Project status

`0.1.0-alpha.2` is a private publication candidate. The repository remains
private while clean-host installation, licensing, ownership, recovery, and
external review requirements are completed. See
[release readiness](docs/RELEASE_READINESS.md) and the
[publication checklist](docs/PUBLICATION_CHECKLIST.md) for the remaining work.

## Documentation

- [Installation](docs/INSTALL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Authentication: Local accounts, OIDC, and Kerberos](docs/AUTHENTICATION.md)
- [Models](docs/MODELS.md)
- [OCR and media](docs/OCR_AND_MEDIA.md)
- [Storage, backup, and restore](docs/STORAGE_AND_BACKUP.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Release readiness](docs/RELEASE_READINESS.md)

## License

The intended project license is Apache-2.0; see [LICENSE](LICENSE). Publication
remains gated on confirmation that the contributing organization may release
all first-party code and that every bundled dependency and model notice is
complete.
