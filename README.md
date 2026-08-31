# RecordBench

RecordBench is a self-hosted, local-first workbench for temporary case and
discovery review. Teams upload the material they need for a matter, process it
with local OCR, transcription, retrieval, reranking, and generation models,
review every answer against cited sources, export work product at any stage,
and close the matter when the workspace is no longer needed.

This repository packages the complete product surface:

- the multi-user matter workbench, membership, audit, conversations, notebook,
  reports, review workflows, exports, and deletion lifecycle;
- PostgreSQL full-text plus pgvector retrieval, learned embeddings, a
  cross-encoder reranker, grounded generation, and verification;
- ClamAV-protected intake plus PDF, DOCX, image, email, spreadsheet, audio, and
  video handling;
- the bundled RecordBench Transcription service: durable queue, WhisperX,
  alignment, optional speaker diarization, media status, transcript exports,
  automatic summaries, cleanup, and optional Transcript Studio UI;
- local accounts, generic OIDC, and Kerberos/Windows Integrated Authentication options;
- configurable local/NAS matter storage, encrypted backup tooling, health
  checks, model staging, and an isolated Docker Compose deployment.

## Status

`0.1.0-alpha.2` is a prerelease private publication candidate derived from the tested
RecordBench 0.1 application baseline. Do not expose it to staff or publish the
repository until the checks in
[docs/PUBLICATION_CHECKLIST.md](docs/PUBLICATION_CHECKLIST.md) pass and the
organization approves the project and third-party licensing record.

No case data, organization secrets, internal accounts, or private deployment
coordinates belong in this repository. The review path uses multi-stage retrieval:
candidate search, learned reranking, grounded generation, and source
verification.

## Quick start

For the CPU evaluation profile, use a Linux host with Docker Compose. NVIDIA
Container Toolkit is required only when selecting a GPU profile:

```bash
git clone <private-review-url> recordbench
cd recordbench
./install
```

The installer starts with loopback-only HTTPS and defaults to CPU evaluation.
It asks how identity, storage, and optional model capabilities should work,
removes any one-time Hugging Face token before runtime, initializes an
administrator, and runs health checks. It also supports:

```bash
./install --help
./install doctor --root /srv/recordbench
./install install --root /srv/recordbench --prepare-only
./install backup --root /srv/recordbench --repository /mnt/backup/recordbench \
  --recovery-key-output /mnt/recovery/recordbench-password
./install update --root /srv/recordbench
```

Read the complete [installation playbook](docs/INSTALL.md) before a staff
deployment. The default generated certificate is only for loopback smoke tests;
LAN access requires an organization-trusted certificate and a deliberate bind.

## Core data rule

RecordBench is a review workspace, not the authoritative evidence warehouse.
Matter bytes live only under the operator-selected managed storage boundary.
Closing a matter can permanently remove its workspace, so users should export
anything they need to retain. Backups are encrypted and retention-limited, and
the standalone transcription queue is deliberately excluded because it is
ephemeral delivery state.

## Documentation

- [Installation](docs/INSTALL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Authentication](docs/AUTHENTICATION.md)
- [Models](docs/MODELS.md)
- [OCR and media](docs/OCR_AND_MEDIA.md)
- [Storage, backup, and restore](docs/STORAGE_AND_BACKUP.md)
- [Security model](docs/SECURITY_MODEL.md)
- [Release readiness](docs/RELEASE_READINESS.md)

## License

The intended project license is Apache-2.0; see [LICENSE](LICENSE). Publication
is still gated on confirmation that the contributing organization may release
all first-party code and that every bundled dependency/model notice is complete.
