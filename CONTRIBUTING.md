# Contributing

Use synthetic data only. Open an issue before changing authentication, storage,
deletion, backup, model, or provenance contracts. Add tests and operator docs
with every behavioral change. Model changes require immutable revisions,
licenses, resource measurements, and representative evaluation—not only vendor
benchmarks.

Before a commit, run the publication sanitizer, the main test suite, the bundled
transcription tests, Python compilation, and Compose validation. Never commit a
real `.env`, key, certificate, keytab, token, database, media file, transcript,
or organization-specific deployment overlay.

With the repository virtual environment at `.venv`, the complete local gate is:

```console
make check
```

GitHub Actions runs the same application, transcription, sanitizer, compilation,
standard Compose, Kerberos overlay, and non-interactive installer contracts. The
workflow actions are pinned to reviewed commit SHAs.
