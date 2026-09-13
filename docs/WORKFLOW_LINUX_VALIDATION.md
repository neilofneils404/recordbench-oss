# Linux validation and feedback handoff

## Returned result

Linux feedback has returned for the exact four-file production patch over
`d43e142769b5d57a901fb58439bf841ed954b8b4`. The original local bundle was unavailable
to the Linux task; it received the patch directly and authored separate synthetic
tests. Its native contributor gate and 25 new checks passed, and its browser
reproduced both baseline failures and verified both corrected workflows. All
returned artifact hashes and production-file hashes match.

See [the returned Linux receipt](WORKFLOW_LINUX_FEEDBACK.md) for commands, totals,
the unrelated baseline fixture failure and remaining limits. This validates the
production patch, not the complete local commit or its 43 new tests. No further
production repair follows from these results. The steps below remain a handoff
for validating the complete candidate when its bundle is actually available;
do not assume access to a local artifact or unpublished Git revision.

## Complete candidate transfer

Validate the exact local review candidate named in the accompanying
`candidate.json`, against public baseline
`d43e142769b5d57a901fb58439bf841ed954b8b4`. The accompanying Git bundle preserves
the reviewed commit identities. It is a transfer artifact, not a release or
deployment instruction. Do not replace an existing application or import its
database/configuration. Use disposable checkouts, runtime directories and the
new synthetic fixtures only.

## Prepare isolated public-source checkouts

Inspect the bundle and its checksum from the delivery manifest. In a public OSS
clone containing the baseline, import its candidate branch locally and create
two new worktrees. Replace the artifact and directory placeholders deliberately:

```console
git bundle verify /path/to/recordbench-workflow-repairs.bundle
git fetch /path/to/recordbench-workflow-repairs.bundle refs/heads/codex/workflow-handoff-20260912:refs/heads/validation/workflow-handoff
git worktree add --detach /path/to/new-baseline d43e142769b5d57a901fb58439bf841ed954b8b4
git worktree add --detach /path/to/new-candidate validation/workflow-handoff
```

Verify `git rev-parse HEAD` in the candidate against `candidate.json`. Do not
silently substitute a later public head. Use Ubuntu 24.04/Python 3.12 and the
contributor prerequisites in `CONTRIBUTING.md`, including Docker Compose,
FFmpeg/FFprobe and PDF extraction tools. The new spoken browser fixture also
requires **espeak** on Linux. Model weights are unnecessary for deterministic
workflow validation. Create each checkout's own development environment using
`make bootstrap`.

## Unadapted Linux gates

Run in the candidate, retaining exit codes and output outside the checkout:

```console
CASE_INTELLIGENCE_STORAGE_RESERVE_GIB=0 make check
PYTHONPATH=src CASE_INTELLIGENCE_STORAGE_RESERVE_GIB=0 .venv/bin/python -m pytest -q \
  tests/test_investigation_candidate_accounting.py \
  tests/test_saved_answer_report_support.py \
  tests/test_saved_answer_payload_budget.py \
  tests/test_workflow_quality_handoff.py
.venv/bin/python scripts/run-browser-acceptance.py --output /tmp/workflow-existing-browser-new
```

Run the same gate with the same bounded test reserve in the baseline too if any candidate gate fails. Record exact
failure node IDs; a baseline-equal failure is diagnostic, not acceptance. Do not
carry the macOS executable/PDF accommodations into Linux. The standalone browser
script chooses those only on macOS and records their status. It uses a bounded
zero storage reserve only for its disposable fixture, as existing browser tests
do. The application command above uses the same test reserve as hosted CI;
production settings are not changed.

Install the repository's checksum-pinned browser/driver into a new temporary
directory, using the existing runner's verified installer:

```python
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("browser_runner", "scripts/run-browser-acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
scratch = Path("/tmp/workflow-pinned-browser-new")
scratch.mkdir()
chrome, driver, version = runner.install_browser(scratch, runner.host_platform())
print(chrome)
print(driver)
print(version)
```

Use those returned executables for the generated-speech journey:

```console
.venv/bin/python scripts/browser-accept-workflow-handoff.py \
  --chrome-binary /path/printed/for/chrome \
  --chromedriver /path/printed/for/chromedriver \
  --output /tmp/workflow-cedar-candidate-new
```

The output must be new. Its receipt must show both jobs `succeeded`, five
candidate/selected passages in the first investigation pass, exact source and
export checks, and no native PDF accommodation. For before/after evidence,
copy only this new browser script and the new test files into the disposable
baseline checkout; keep baseline `src/` untouched. Run the same browser command
there with a different output and `--expect-baseline-rejection`. It must identify
the exact saved-text and checkpoint errors, with three candidates/five selected
for the old investigation. Remove neither source verification nor counter checks.

A browser timeout or tool prerequisite failure is a test-harness/infrastructure
result until a minimal application reproduction proves otherwise. Retain its
stage and exit code; do not label it a product defect from the timeout alone.

## Actual-model quality and application review

The deterministic fixtures do not establish learned relevance or semantic
usefulness. Follow `docs/WORKFLOW_QUALITY_HANDOFF.md` for the 30-source corpus,
fixed gold labels, conservative metrics and seven-dimension semantic rubric.
Its optional evaluator requires an already available local model, exact model
name and immutable artifact digest. It starts or downloads no model. Run the
provided question and unsupported purchase-order control with the actual
application as a separately labeled experiment. Inspect extracted source packets
before interpreting missed relevance. Keep machine decisions, human overrides,
and prior saved work distinct.

In the synthetic application, additionally verify PDF-only, transcript-only,
mixed and individually saved note compilation. Open the exact PDF page and
recording moment from both saved work and Report citations. Inspect downloaded
Word and Markdown text. Edit transcript text through the supported application
workflow and verify that old support cannot silently authorize changed text.
Exercise the documented new-conversation recovery while preserving the original
conversation, note and failed investigation.

## Return this feedback to the coding task

Return a sanitized report with these fields. Supply newly authored reproduction
text only; no original environment evidence or access is needed.

```text
Candidate SHA and bundle SHA-256:
Baseline SHA:
OS distribution/version, CPU architecture, Python and browser versions:
Synthetic fixture/evaluator fingerprint:

Contributor gates: command, exit code, passed/failed/skipped totals.
Candidate failures: exact pytest node IDs and concise content-free errors.
Same nodes on baseline: pass/fail/unavailable, with command and revision.
Browser receipt checks: pass/fail and first failing stage.
Investigation: job state; pass candidate/source/selected/new/analyzed counts;
  duplicate, empty, unavailable and resume outcomes.
Mixed Report: PDF-only/transcript-only/mixed/note matrix; saved text basis;
  exact original-source navigation; Word/Markdown retained support.
Transcript edit: stale compile/copy/export rejection; recovery result;
  confirmation that prior work and history remain intact.
Quality: actual model name + immutable digest and settings; TP/FP/FN/unresolved;
  false-negative synthetic case IDs; packet text and machine rationale;
  independent 0/1/2 semantic scores with a brief rationale for each dimension.
Discovery: mention/suggestion/label counts; distinct-candidate separation;
  source navigation, manual merge and Undo outcomes.
Unexpected behavior: exact synthetic action sequence, expected versus actual,
  smallest new fixture, reproducibility count, and whether a model was called.
Untested/blocked: prerequisites or reason; no inferred product conclusion.
```

Before returning artifacts, remove hostnames, absolute runtime paths and identity
metadata that test tools can add even to synthetic runs. Prefer the bounded JSON
browser receipts, sanitized failure-node summaries and synthetic excerpts over
raw runtime databases, complete logs or deployment configuration. Preserve
original local diagnostics separately so a redacted summary does not erase
evidence. Return this feedback to the original coding task for the next bounded
repair; Linux validation alone does not authorize merge or deployment.
