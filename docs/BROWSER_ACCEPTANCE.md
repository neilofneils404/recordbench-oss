# Synthetic browser acceptance

The `synthetic-browser` job in the quality workflow runs the existing intake
receipt and Report bundle journeys on Ubuntu 24.04 and Python 3.12. Reports
always include `--verify-readiness`: the browser checks export preview, missing
source repair, cross-matter denial and interrupted-close recovery as well as
Markdown/Word downloads. The Report script enters the visible reading/editor
views and expands the blank-document and written-section controls before editing.

Both applications are generated for the run and listen on ephemeral loopback
ports. They use the unavailable generator and synthetic text fixtures. This is
not a model-quality, media-codec, live PostgreSQL or deployed-node acceptance
check. No model weights or external evidence are downloaded. Production resource
settings are not changed: the runner supplies a zero storage reserve only to its
small disposable test applications.

## Contributor commands

Install the normal contributor Python dependencies first. On Ubuntu 24.04 install
the browser libraries listed in `.github/workflows/quality-gates.yml`. Then run:

```console
.venv/bin/python -m pytest -q tests/test_browser_acceptance_runner.py
.venv/bin/python scripts/run-browser-acceptance.py --output /tmp/generated-browser-acceptance
```

The output directory must not exist. Use a new name on each attempt; the runner
will not replace old receipts or treat them as evidence of a new successful run.
Linux x86_64 and Apple Silicon macOS have pinned archives. Unsupported hosts fail
before any journey starts. All temporary paths passed to the applications are
resolved, including on macOS where the system temporary directory can traverse a
symlink.

The default timeout is 300 seconds **per journey**, configurable with
`--timeout-seconds 1..600`. Each journey runs in its own process session. On
success, failure, timeout, SIGINT or SIGTERM the runner terminates that process
group, gives it a short grace period, kills remaining members and reaps the
leader. A nonzero child exit fails even if it left a success receipt. Missing,
malformed, failed, nonsynthetic or incomplete receipts also fail. An ordinary
journey failure still runs the other journey; interruption stops the run. The
runner tests exercise these failure contracts with generated subprocesses and
receipts, without downloading or opening a browser.

The runner starts children with fresh home, temporary and cache directories,
offline model flags and a small environment allowlist. Deployment settings,
proxy credentials and Python import overrides from the calling shell are not
inherited. Browser and driver paths are explicit, so Selenium Manager is not
used to resolve or install a different version.

## Browser pins and deliberate updates

`config/browser-testing.json` records one exact Chrome for Testing version,
matching ChromeDriver URLs and SHA-256 hashes for each supported platform. The
initial archives come from Google's [Chrome for Testing availability
index](https://googlechromelabs.github.io/chrome-for-testing/). SHA-256 values were
computed from the downloaded versioned archives and checked into the repository;
there is no runtime lookup of a moving stable/latest channel. Every archive is
verified before extraction or execution. ZIP paths, framework symlinks and total
expanded size are checked before any browser starts.

For an offline replay, download both named archives beforehand and pass their
directory with `--archives /path/to/verified-archives`. The same committed hashes
are checked on every run. Archives and extracted browsers stay outside the
artifact output. They are not committed or uploaded.

To update the browser intentionally:

1. Choose a specific available version from the official index and obtain both
   Chrome and ChromeDriver archives for each supported platform.
2. Compute each SHA-256 locally, update the version, URLs and hashes together,
   and inspect that all URLs identify the same exact release.
3. Run the runner tests and both real journeys. Require the actual hosted
   `synthetic-browser` PR job to pass, and review its bounded receipts and
   screenshots before accepting the update. A unit-test pass alone does not
   qualify a browser update.
4. Keep the update in a reviewable commit. For rollback, revert the pin update
   as a new commit and rerun the same gates; do not change a release tag or
   replace a hash to silence a failed download check.

## Retained diagnostics

The intake journey uses nonblocking Chrome navigation. Explicit reloads wait
for the old document to detach and the replacement document to finish loading
before checking receipt rows or reselecting an interrupted upload. A stalled
reload fails within the existing browser wait deadline.

The runner copies only an explicit allowlist of generated receipts, screenshots,
failure HTML and browser-error JSON, plus the last 256 KiB of each child log.
Receipts and browser-error JSON are limited to 64 KiB each; other allowed files
to 2 MiB each, with a 16 MiB total copy budget. Oversized and nonregular files
are omitted and listed in `journeys.json`. The small `summary.json` and
`journeys.json` are additional runner metadata. The output never recursively
copies a journey directory. Runtime databases, browser profiles, downloaded
archives and exported bundles are excluded. CI uploads only this sanitized
output directory and retains it for five days, including when a journey fails.

Check `summary.json` first, then the failed journey's log and screenshot. A
receipt proves only the generated steps recorded in its `checks` array. CI
application/transcription tests, final-commit code/security reviews and the
maintainer merge gate remain separate requirements.
