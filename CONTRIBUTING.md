# Contributing

Use synthetic data only. Open an issue before changing authentication, storage,
deletion, backup, model, or provenance contracts. Add tests and operator docs
with every behavioral change. Model changes require immutable revisions,
licenses, resource measurements, and representative evaluation—not only vendor
benchmarks.

Install the [pre-push publication check](docs/PUBLIC_ALPHA.md#prevent-disclosure-before-publishing)
before your first push. Public issues, PR descriptions, comments, attachments,
screenshots, and logs are also publication surfaces; the Git hook cannot scan
uploads made through GitHub's website or API. Never copy private deployment
history or output into them. Start with the [contributor backlog](docs/CONTRIBUTOR_BACKLOG.md).

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

## Development model

RecordBench OSS is the upstream source for portable product behavior. Work from
a focused branch or worktree, keep one reviewable concern per change, and merge
only after its synthetic regression and relevant operator documentation pass.
Do not develop reusable behavior only inside a private deployment and copy its
history back later.

If an issue is discovered in a downstream deployment:

1. describe the behavior without private source material, logs, paths,
   identities, hostnames, or configuration;
2. reproduce it here with an unmistakably synthetic fixture;
3. implement and validate the general correction in this repository; and
4. let the downstream record and consume the resulting reviewed revision.

Downstream-specific identity mappings, certificates, storage coordinates,
capacity policy, secrets, and service wiring belong in an external deployment
overlay. They are not acceptable additions to this repository even when the
downstream is private.

## Pull requests

Wait for GitHub-hosted Codex code and security reviews on the final commit,
reconcile every finding, and pass required CI before merge. Corrections require
renewed review. Local review does not replace those hosted reviews. Maintainers
must also inspect synthetic-data provenance and disclosure risk. See
[merge and automation controls](docs/PUBLIC_ALPHA.md#merge-and-automation-boundary).

Each pull request should explain the user problem, the resulting behavior, the
synthetic evidence, and any security, lifecycle, migration, model, or recovery
impact. Use the repository pull-request template and keep release tags
immutable. A correction after a release is a new commit and, when appropriate,
a new release.
