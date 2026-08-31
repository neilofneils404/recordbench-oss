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
- Ask focused questions and receive answers tied to source passages rather
  than an unsupported block of generated text.
- Research a broader issue across a collection or review every source against
  defined criteria while preserving coverage and human-review status.
- Keep conversations, notes, people, places, dates, reports, and other work
  product organized inside the matter.
- Export answers, conversations, transcripts, summaries, clips, notebooks,
  reports, and complete matter work product.
- Close and delete a temporary matter when the work is finished.

## Four ways to review

| Workflow | Use it when you need to… |
| --- | --- |
| **Ask** | Answer a focused question with citations to the strongest matching material. |
| **Research** | Explore a broader topic through multiple searches while keeping an evidence and coverage record. |
| **Full Review** | Apply the same review question to every source in a frozen collection and validate the results. |
| **Review Sources** | Read extracted documents, inspect processing problems, play media, and work directly with transcripts. |

This separation is deliberate. A quick cited answer, an open-ended research
task, and a source-by-source review are different jobs and should not be
presented as the same chat box.

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
| **Full review and media** — document review plus transcription and optional diarization | 16 cores | 64 GB | 1 GPU with 24 GB VRAM | 300 GB |

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
