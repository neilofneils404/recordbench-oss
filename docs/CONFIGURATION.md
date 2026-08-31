# Configuration

`compose.env` controls host paths, ports, GPU assignment, and the pinned model
portfolio. `config/recordbench.env` controls application behavior.
`config/transcription.env` controls the bundled media queue and worker. The
installer writes all three outside Git with mode `0600`.

Secrets are separate owner-only files: PostgreSQL password/DSN, local account
hashes, transcription API token, OIDC client secret, or Kerberos keytab/proxy
secret. A real secret must never appear in an environment example.

Key operator decisions include:

- `RECORDBENCH_STORAGE_ROOT`: dedicated matter byte boundary;
- `RECORDBENCH_MODEL_ROOT`: offline model cache;
- `RECORDBENCH_*_GPU`: detected or explicitly selected physical GPU assignment;
- `RECORDBENCH_GPU_LAYOUT`, retrieval device, and generator tensor-parallel
  width: portable shared, separated-role, or operator-overridden topology;
- generator dtype, memory share, batch size, and application concurrency are
  derived conservatively from compute capability and whether transcription is
  co-resident;
- `CASE_INTELLIGENCE_*_QUOTA_*`: per-matter, upload, file, and reserve limits;
- OCR language/page cap and ingestion/answer concurrency;
- generator backend/endpoint/model and exact allowed companion-service hosts;
- transcription retention, capacity, diarization, and free-disk reserve.

Do not edit generated files while services run. Back up, validate changes with
`docker compose config`, restart only affected services, and rerun the doctor.
