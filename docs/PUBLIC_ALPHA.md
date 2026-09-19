# Public contributor alpha

The maintainer authorizes publication of the environment-neutral source as a
development alpha. This is distinct from a supported production release.
First-party Apache-2.0 approval is recorded in [release readiness](RELEASE_READINESS.md).
The repository does not publish private deployments or represent an operator's
endorsement. No model weights, credentials, or live evidence are distributed.

## Publication requirements

Before visibility changes, the maintainer checks the exact candidate and every
published branch, tag, and pull-request history; uses the generic sanitizer,
an independent secret scanner, and a private operator deny list kept outside
the repository; reviews synthetic media and third-party notices; and inspects
GitHub descriptions, discussions, logs, artifacts, releases, and settings.
False positives require a narrow, recorded disposition rather than removal of
the underlying check. New public author identities are deliberate and should use GitHub
no-reply email addresses. The maintainer explicitly accepted the existing
author/committer email on commit `d2f1e779e70063b94fece1291169f547c7c44d83`.
The scanner records that reviewed attribution by exact commit and identity
digest, suppressing only the non-example-email finding for those metadata
fields. It does not permit the address in file content, commit messages, other
commits, or unrelated identities. Operator deny terms still apply unless the
operator explicitly supplies the same exact commit/name/email through the
existing baseline-identity option. For this reviewed personal attribution, that
option covers only the named commit, never its ancestors. Keep the private audit and its deny terms outside Git.

Source publication does not ship a production image or promise installation,
hardware, recovery, legal accuracy, completeness, or confidential-workload
acceptance. The full supported-release requirements remain in
[release readiness](RELEASE_READINESS.md). Optional dependencies and models
have separate upstream terms; see [third-party notices](../THIRD_PARTY_NOTICES.md).

The maintainer also approved the exact author attribution on merge commit
`4b8d74be09f41a443abb705bed1c6ab8bb5371c7`. Its disposition follows the same
commit-and-identity boundary above and grants no exception to later commits.

When using the GitHub CLI to merge, explicitly pass `--author-email` with the
public no-reply address validated for the reviewed head. The account default may
use a personal address even when local commits use no-reply attribution. If
GitHub rejects the public address, use a normal protected fast-forward of the
reviewed head when possible; do not remove branch protections or silently retry
with the account default.

## Prevent disclosure before publishing

CI runs after content reaches GitHub. It cannot prevent an initial disclosure.
Install the local pre-push check in every publishing checkout:

```console
python3 scripts/install-publication-hook.py ~/.local/share/recordbench-publication-guard/reviewed-v1
```

Run the installer from a trusted, reviewed checkout with the Python environment
that contains the scanner dependencies. Both that environment and the new
installation directory must be outside the publishing checkout. Interpreter
symlinks must also resolve outside it. The installer
copies the reviewed scanner and hook, pins the interpreter, and enables isolated
Python execution for both hook and scanner, removing inherited Python environment
variables from the scanner process. Branch switches cannot replace this installed code. Reinstall
reviewed updates into a new directory. Do not point `core.hooksPath` at the
branch-owned `.githooks` directory.

The hook scans every outgoing branch/tag and its reachable history in an
isolated temporary repository before Git transmits objects, including every
reachable annotated tag object. CI also runs on tag pushes. Install `pypdf`
and `ffprobe` as described in the publication checklist; missing inspection
dependencies block publication. The exact public GitHub merge-service email is recognized; other non-example
addresses and configured deny terms still block. A removed file still exists in history and
still blocks. Keep sensitive work in a separate repository with no public
remote. Never use mirror pushes or push private deployment histories.

Operators developing alongside private deployments must additionally configure
an owner-only deny file outside the checkout:

```console
git config --local recordbench.requirePrivatePublicationCheck true
git config --local recordbench.publicationDenyFile /secure/path/private-deny.txt
```

Exact public clone URL and author-identity exceptions use the scanner's
documented adjudication options. The hook reads `recordbench.publicCloneUrl`,
`recordbench.publicGitIdentity` (tab-separated name/email), and
`recordbench.publicBaselineIdentity` (tab-separated commit/name/email).
Do not add general exceptions for private names or paths.

Hooks are local safeguards, not a security sandbox: another client, an API
upload, or `--no-verify` can bypass them. Maintainers must not bypass the check.
Review outgoing issue/PR text, comments, screenshots, attachments, workflow
logs, package metadata, and release assets separately before upload. Never
paste production output into a public report, even when filing a bug. Use a
content-free description and reproduce it with synthetic material.

GitHub secret scanning/push protection covers supported secret patterns, not
arbitrary private case facts. A passing scan is evidence of checks performed,
not a guarantee that all confidential information was recognized. If a leak is
suspected, stop publishing and report privately; removing it in a later commit
does not remove public copies or history. Revoke exposed credentials first.

## Merge and automation boundary

Keep the default branch protected with required Quality CI, `hosted-review-gate`,
resolved discussions, at least one native PR approval, stale-approval dismissal,
approval of the most recent push, and no force pushes or deletion. Application,
PostgreSQL integration, synthetic-browser, transcription, deployment-contract
and secret-scan Quality gates remain mandatory; this policy does not remove or
weaken any Quality check.

Hosted Codex review is an optional maintainer tool. Local/maintainer review is
sufficient when Quality is green and protections allow merge. By default,
`hosted-review-gate` publishes success with “Hosted review not required” without
reading or waiting for Codex results. It still submits a native policy approval
bound to the individual PR, full head and base so the existing required status
and approval do not become dangling requirements. This approval records policy
eligibility only, not a completed code or security review. Branch conversation
resolution and other native protections still apply independently.

A maintainer opts a PR into strict hosted review by adding the exact label
`require-hosted-review`. Review commands (`@codex review` and
`@codex security review`) alone request advisory review and do not opt in.
Adding the label does not launch reviews; request them deliberately. Removing
the label restores the default optional policy only when the removal actor has
current write, maintain or admin permission. The gate reconstructs label history
and fails closed if history is unavailable. A triage-level removal cannot disable
strict review; a maintainer can add and remove the label again to authorize
opt-out. Both label events rerun the workflow. Keep automatic code review disabled in the Codex GitHub integration's
repository settings; Actions policy does not control that separate setting.
No repository workflow posts review commands on open or synchronize.

Policy changes on an already-open PR require the
[draft-first procedure](../CONTRIBUTING.md#pull-requests): disable auto-merge,
convert the PR to draft and confirm that state before changing the label. Keep
it draft until the resulting gate run finishes and publishes the new policy's
status and native review. A failed run leaves the PR draft until corrected.
Label events alone are not an atomic merge barrier; the synchronous draft
transition prevents the old approval from authorizing a merge while Actions
queues. Only return the PR to ready after that revalidation.

For opted-in PRs, the gate requires completed GitHub Codex code and security
reviews on the current head (or the narrow security-quota exception below),
review discussions reconciled by someone with write, maintain or admin access,
and later full-head maintainer acceptance. Local review does not substitute for
those explicitly required hosted reviews. Changed heads and newer requests
require renewed review; edited requests invalidate earlier completions. A
withdrawn request no longer counts, but already-recorded running security state
still blocks until reconciled. Unknown review-summary formats fail closed.
After resolving discussions, dispatch the Hosted review gate workflow with the
PR number if a new evaluation is needed.

In both modes, the status and native approval are required by existing branch
protection and apply to PRs targeting the default branch. Shared commit status
cannot grant another PR native approval. The gate withdraws its prior approval
before reevaluation, then checks head, base and opt-in state around approval.
Changes during approval withdraw the new approval and require reevaluation.
Keep strict up-to-date status checks enabled. A default-branch advance requires
an updated head and fresh CI, plus fresh hosted review when opted in. The gate
uses pull-request write permission, not repository-admin dismissal rights.

The gate reads trusted default-branch code and GitHub metadata only; it never executes the PR head
with a write token. External contributor workflows require
maintainer approval. Use hosted runners with synthetic fixtures; do not attach
private infrastructure or deployment credentials to public Actions. Default
workflow permissions are read-only and actions are pinned to full commits.
Enable GitHub Actions PR-review approval capability for this trusted workflow;
only this gate requests pull-request write permission.

For an opted-in PR, after both hosted reviews finish, or after code review and the verified
security-quota exception below, a maintainer independently checks the full
current head and review results, then posts this exact one-line PR comment,
replacing the placeholder with the complete 40-character commit ID:

```text
RecordBench maintainer acceptance: FULL_COMMIT_ID
```

The acceptance timestamp must be strictly later than both review completions
(or the code completion and quota-exception comment) and come from an account
with current write, maintain or admin permission. This additional full-commit
acceptance is required because the code-review summary abbreviates its commit
ID; a matching short prefix alone is not sufficient. A changed head, a newer
review completion, or removal of the acceptance requires renewed acceptance.
Missing acceptance leaves the gate pending. The gate verifies current access
through GitHub, rather than trusting the comment's displayed association.

The maintainer still reviews disclosure, provenance, and reconciled findings.
Outside contributors do not need or receive access to a private deployment.

### Security-review quota exception

This exception applies only to PRs labeled `require-hosted-review`.

A maintainer may proceed when GitHub Codex explicitly cannot start security
review because its security-review quota is exhausted. This is a recorded
exception, never a claim that security review passed. Completed current-head
code review, required CI, reconciled discussions, native gate approval, strict
up-to-date protection and no-reply publication checks remain required.

On the PR, request security review with these exact two paragraphs, replacing
the placeholder with the full current head:

```text
@codex security review

RecordBench security review head: FULL_COMMIT_ID
```

After the official Codex bot replies with its explicit security-review usage
limit message, inspect the full head and all review findings. Record this exact
one-line exception using the numeric issue-comment IDs of that request and bot
response on this PR:

```text
RecordBench security quota exception: FULL_COMMIT_ID; request: REQUEST_COMMENT_ID; response: RESPONSE_COMMENT_ID
```

Then post the ordinary full-head maintainer acceptance above, strictly after
both the code-review completion and exception. The gate verifies live write,
maintain or admin permission for the request, exception and acceptance authors.
It requires the official bot identity, exact quota message, matching full head,
and request-before-response-before-exception timestamps. Editing an old request
cannot reuse a previous response. Removed evidence or a changed head invalidates
the exception. Any other security request at or after the bound request time needs its own completion or quota receipt, including requests before the referenced response and ambiguous same-second requests.

This path applies only when the latest official review summary has no security
review row or security metadata. Recorded running, failed, malformed or stale
security-review state must be reconciled through hosted review; quota cannot
override it. Quota handling requires the complete known code-only summary in order: its header, exact table shape, completed code row and fixed help footer. Missing, reordered or additional content requires diagnosis. The code timestamp and commit prefix are read from their specific fields. The native approval and status explicitly identify the exception.
No local review substitutes for required hosted code review. Branch protections
are not disabled to apply an exception.

The policy landed in [#71](https://github.com/neilofneils404/recordbench-oss/pull/71)
at `17eafce965062e9fbdf8884738e277573abc8f7f` after a one-time installation
from the immutable protected tag `recordbench-quota-policy-bootstrap-20260912-v1`.
The scoped bootstrap dispatch has been removed from the current workflow.
Retain that historical tag and its update/deletion protection without bypass
actors. All later quota exceptions use the ordinary default-branch gate.

The gate withdraws its prior native approval when a PR moves away from the
default branch. Publication identity dispositions support SHA-1 and SHA-256
repository object IDs.
