# Standalone browser acceptance

Status: implementation and local generated acceptance; a successful hosted PR
run and final-head review are required before merge. Contributor automation only.

## Scope and commands

The standalone **Browser acceptance** workflow runs the existing intake receipt
and Report bundle journeys on branch pushes and pull requests. The latter also
checks export readiness. Both create generated loopback applications with an
unavailable model, temporary storage and ordinary browser upload, source opening,
work-product editing, recovery and export. The hosted job has no model downloads,
private services or external evidence. Model access is offline during this job.
Media codec journeys and isolated PostgreSQL checks remain separate work.

On supported Linux, bootstrap the contributor environment and install the pinned
browser pair into a new directory whose parent already exists:

```console
make bootstrap
./scripts/install-test-browser.sh /tmp/recordbench-test-browser
.venv/bin/python scripts/browser-acceptance.py \
  --chrome-binary /tmp/recordbench-test-browser/chrome-linux64/chrome \
  --chromedriver /tmp/recordbench-test-browser/chromedriver-linux64/chromedriver \
  --output /tmp/recordbench-browser-results
```

The workflow lists Ubuntu 24.04 browser libraries, fonts, curl, unzip and ffmpeg.
The runner requires the same exact pinned version for browser and driver and a
new output directory; an existing result is preserved and cannot authorize another
run. Each journey has a 300-second default timeout (`--timeout` accepts 1–600).
Both journeys run even when the first fails, preserving useful failure evidence.
An error, timeout or missing/incomplete/failed receipt makes the runner fail.
Normal completion, interruption and timeout stop the command's process group,
including leftover browser/driver processes. A killed runner cannot report success.

## Pin and intentional updates

Chrome for Testing and ChromeDriver are pinned together at **152.0.7977.82**.
The [official availability list](https://googlechromelabs.github.io/chrome-for-testing/)
identified this stable release on September 8, 2026. Official Linux archives were
downloaded from the versioned Google storage paths and their SHA-256 digests
recorded in `scripts/install-test-browser.sh`. The installer verifies both before
extracting either. `scripts/browser-acceptance.py` checks actual binary versions.
Chrome/ChromeDriver are test prerequisites downloaded separately, not shipped
application assets or new Python dependencies.

To update, choose one matching pair from the official list, download its versioned
archives, inspect and record their hashes, update the installer and runner pins,
and run the runner regressions, both actual journeys and the hosted PR job. Do not
resolve a floating stable/latest version during CI. Keep the existing version until
its replacement has passed. Installer failure leaves its new directory available
for inspection; use another new directory for a subsequent attempt.

## Hosted evidence and recovery

The workflow uses the integration checkout verified against the event SHA,
read-only permissions, pinned actions and an ordinary hosted Ubuntu runner.
The job is named `browser-acceptance`; repository administrators select required
status checks separately. Generated evidence is retained for seven days as an
Actions artifact: overall/journey results, acceptance receipts, screenshots,
runner logs and failure HTML/browser errors. The upload paths exclude runtime
stores and downloaded bundles. Missing setup-stage artifacts do not turn a failed
job green. These fixtures are synthetic and suitable for public contributor CI;
never repurpose the job or artifact paths for confidential material.

Inspect the failed journey's `runner-result.json` and `runner.log`, then reproduce
with the same browser pair and a fresh output directory. Correct the cause and
rerun. Do not reuse an older passing receipt or dismiss an application error as a
browser failure. Rollback removes contributor automation and leaves application
state unchanged; old generated artifacts expire under their retention setting.

## Local evidence

Ten runner/installer regressions pass: fresh complete success; command failure;
missing, invalid, failed or incomplete receipts; refusal to reuse old output;
timeout and normal-exit descendant cleanup; and rejection of corrupted archives
before extraction. Positive installation also verifies both recorded archive
hashes and starts the matching binaries.

The first pinned-browser run correctly failed on a navigation race in the intake
harness while the Report journey passed. Reading the current document atomically
fixed that wait without weakening workflow assertions. A later keyboard-reorder
navigation in the Report harness needed its existing detached-node predicate too;
its section-order and export assertions remain intact. Both generated journeys
then passed, **11 intake checks and 11 Report/export-readiness checks**. The run
also exposed an upload-status race, addressed separately before final combined
acceptance; see [upload status recovery](UPLOAD_STATUS_RECOVERY.md).

Final combined contributor checks and actual PR execution are recorded before
merge. No live deployment or release tag is created by this workflow.
