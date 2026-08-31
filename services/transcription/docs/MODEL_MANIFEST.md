# Approved model manifest

Real WhisperX workers fail closed unless `TRANSCRIPTION_V2_MODEL_MANIFEST`
verifies successfully. The manifest itself and every listed artifact must be
inside `TRANSCRIPTION_V2_MODEL_CACHE`. Absolute paths, `..`, symbolic links,
missing/non-regular files, unexpected byte sizes, and SHA-256 mismatches are
rejected before the model engine is constructed. Mock workers do not inspect
the cache.

The strict v1 JSON shape is:

```json
{
  "schema_version": "transcription-v2-model-manifest-v1",
  "artifacts": [
    {
      "role": "asr",
      "model_id": "owner/model-name",
      "revision": "exact-release-or-snapshot-commit",
      "license": "SPDX-or-reviewed-license-name",
      "files": [
        {
          "path": "models--owner--model/snapshots/exact-commit/model.bin",
          "size_bytes": 123456,
          "sha256": "64-lowercase-or-uppercase-hex-characters"
        }
      ]
    }
  ]
}
```

Use one artifact entry per approved role/model/revision and list every runtime
weight, configuration, tokenizer, vocabulary, and other required model file.
`revision` must be pinned; `main`, `master`, `latest`, and `HEAD` are rejected.
The same relative file may appear in multiple roles only when its declared size
and digest are identical. Keep the cache and manifest read-only to the runtime
account after the separately approved staging process.

Community-1 must use the exact role `diarization` and model ID
`pyannote/speaker-diarization-community-1`. Its artifact must cover the regular
cache blob behind the configured pinned snapshot `config.yaml`, as well as every
other file required by that snapshot. A present but unlisted YAML file does not
authorize speaker separation.

Run the read-only gate before starting a real worker:

```bash
transcription-v2 verify-models
```

Exit status is zero only when every file verifies. JSON output includes stable
failure codes or, on success, model/revision/license metadata, aggregate file
counts and bytes, and the manifest SHA-256. It never emits local paths, file
contents, access tokens, or dependency exception text. This command does not
download, move, repair, or otherwise stage models.
