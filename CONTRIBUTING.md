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

## Set up a development checkout

The complete development gate is exercised on Ubuntu 24.04 with **Python 3.12**.
The application requires 3.12 or newer, but the bundled transcription package
requires a version below 3.13, so their shared environment currently needs 3.12.
The contributor tests do not require a GPU or downloaded model weights.
To run the deployed application, use the separate [installation playbook](docs/INSTALL.md).

Clone your fork and enter the repository. Before committing, configure Git
with your public GitHub username and the no-reply address shown in your GitHub
email settings (`git config user.name` and `git config user.email`). Ordinary
personal addresses are rejected by the publication check unless explicitly
reviewed by a maintainer. Then install the host tools. On a fresh
Ubuntu 24.04 development machine:

```console
sudo apt-get update
sudo apt-get install --yes git make python3.12 python3.12-venv \
  ffmpeg imagemagick poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa
```

Install Docker Engine with the Compose v2 plugin using Docker's instructions
for your distribution. Verify `docker compose version` before running the full
gate. These are development-machine prerequisites; the bootstrap never installs
system packages, starts services, or downloads model weights.

From the repository root:

```console
make bootstrap
make check
```

Bootstrap creates `.venv`, installs the application and bundled transcription
service together in editable mode (including test, PostgreSQL, and browser
client dependencies), then runs `pip check`. Package installation requires access
to a Python package index. A browser and matching driver must be available
separately for browser acceptance; installing Selenium alone does not install
Chrome. Optional integration tests can skip when their prerequisites are absent.
`make check` runs compilation, Compose validation, publication inspection,
application tests, and transcription tests. Bare `make` still runs application
tests; it does not install anything.

It is safe to rerun bootstrap with the same interpreter after dependency metadata
changes. An existing incompatible or broken environment is left untouched:
choose a new `--venv` directory. The script never deletes an environment or
silently replaces its interpreter. If a download or install fails, correct the
reported problem and rerun the same command; readiness is printed only after
all installation and dependency checks succeed.

`SYSTEM_PYTHON` chooses the interpreter for `make bootstrap`:

```console
make bootstrap SYSTEM_PYTHON=/usr/bin/python3.12
```

Alternatively, the script can be launched by an older Python while selecting
Python 3.12 explicitly. Custom environment paths, including absolute paths and
paths containing spaces, work with all Make test targets:

```console
python3 scripts/bootstrap-dev.py --python python3.12 --venv "/tmp/recordbench dev"
make check PYTHON="/tmp/recordbench dev/bin/python"
```

Use `--dry-run` to inspect the selected/existing interpreters and preview commands
without creating or modifying an environment or installing packages:

```console
python3 scripts/bootstrap-dev.py --python python3.12 --dry-run
```

The printed commands are for the repository root. Windows contributors should
use a Linux development environment such as WSL2 for the complete gate; native
Windows setup and the full native Windows suite have not been validated.
The bootstrap's Windows interpreter-path support alone is not that validation.

GitHub Actions installs and reruns the same bootstrap, then runs application,
transcription, sanitizer, compilation,
standard Compose, Kerberos overlay, and non-interactive installer contracts. The
workflow actions are pinned to reviewed commit SHAs.

## Development model

Tests that start background workers must respect their job ownership and the
workspace transaction lock. Prefer public workflow transitions over direct SQL
to establish retry states. If a fixture manually claims and completes a job,
stop and join that job's coordinator before queueing it; retain live workers in
tests that exercise automatic processing. A passing rerun alone does not fix a
fixture race.

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

## Standalone browser journeys

The quality workflow also runs the synthetic intake and Report/export-readiness
journeys with a checksum-pinned browser and driver. See
[browser acceptance](docs/BROWSER_ACCEPTANCE.md) for local commands, bounded
artifacts, deliberate browser updates and rollback. These journeys use disposable
loopback applications and require no model downloads or deployment access.
