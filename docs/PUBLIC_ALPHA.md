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

The maintainer approved the existing attribution on commit
`f8ccae72b39704942c23caecb8195874a74e7699` under the same exact-commit and
identity-digest rule. This historical disposition does not rewrite published
history. New commits and merges must use the responsible contributor's validated
GitHub no-reply attribution; this exception does not authorize later
personal-address attribution. Contributors use their own public GitHub username
and no-reply address and retain credit for their work. A maintainer's identity
applies only to commits created by that maintainer or on their behalf; it is not
an identity requirement for outside contributors. Preserve contributor authorship
when landing a PR, and use the maintainer's no-reply identity for any new merge
commit the maintainer creates. Publication checks, review requirements and branch
protections apply to every contributor.

The maintainer explicitly accepted keeping merge commit
`a8f4fbe36439a374746f9c2b2ca9660d89793044` in public history with its existing
author attribution. Its disposition uses only that exact commit and identity
digest, with the same metadata-only boundary above. It does not authorize any
future use of that attribution or relax operator deny checks. Do not use a merge
endpoint that cannot enforce the validated no-reply author; use the explicit
CLI author option or protected fast-forward procedure below.

Exact-commit public merge adjudications also recognize a complete
`Co-authored-by` trailer for a configured, validated GitHub no-reply identity.
Other message text, identities and commits retain the operator deny checks.
The Nemotron dependency lock has one exact package/version-line disposition for
a reviewed public CUDA dependency version that resembles a private IP address;
other files, package names, endpoints, secret rules and deny terms remain checked.

When using the GitHub CLI to merge, explicitly pass `--author-email` with the
public no-reply address validated for the reviewed head. The account default may
use a personal address even when local commits use no-reply attribution. If
GitHub rejects the public address, use a normal protected fast-forward of the
reviewed head when possible; do not remove branch protections or silently retry
with the account default.

The maintainer approved the existing author attribution on squash merges
`624fbe4dcfbae093c442955bfb6cc4b6be6fff3e` and
`6735691a938e42173c6c7a309b700be2e19c0668` for the October 9 merge train.
Each recorded disposition covers only its exact commit and identity digest.
It does not permit email addresses in content or messages, cover other commits,
or relax operator deny checks. The recorded dispositions do not change account
email or privacy settings.

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
approval of the most recent push, and no force pushes or deletion. The Quality
workflow and existing required check names remain mandatory. Code, tests,
dependencies, migrations, configuration and CI changes run the full application,
PostgreSQL integration, synthetic-browser, transcription and deployment-contract
suites. Proven plain documentation-only changes use the bounded
[documentation fast path](QUALITY_GATES.md): expensive suites are explicitly
not applicable, while the required application check verifies successful scope
classification and exact-head publication scanning. Secret scanning and native
review protections always remain required. Unknown scope runs the full gates;
failed classification or publication scanning blocks the required check.

Actual hosted Codex **code review is mandatory on the final implemented head**
for every PR targeting the default branch, including documentation-only PRs.
Local review, review of a plan, a request without completion, an earlier head,
labels and quota messages cannot replace it. `hosted-review-gate` waits for the
official Codex bot's completed current-head code-review summary, reconciled
review discussions and later full-head maintainer acceptance. Unknown or
incomplete code-review summary formats fail closed. The completed CODE row must match the current head's
prefix, but that is only a consistency check. Bind actual review by either:

- An official submitted, non-dismissed native CODE review whose API `commit_id`
  equals the full current head, following the latest CODE request and no later
  than the summary's completion. Its abbreviated prose is not the binding.
  A full SHA directly in the official completed CODE row is also sufficient.
- For clean comment-only results, the explicit trusted verification in the
  acceptance below. The gate checks the specific official clean-result comment,
  full-head request, timestamps and live maintainer permission. It does not claim
  that the provider's short SHA proves which complete commit ran.

Native review IDs identify records, not immutable bodies: body edits require
renewed acceptance. Conflicting native CODE commit evidence cannot be overridden
by clean-result attestation. Missing, deleted, edited or stale clean/request
records cannot be reused; request a fresh review if needed. SECURITY records
cannot satisfy either CODE path. Changed heads and newer or
edited code-review requests require renewed review. A withdrawn request no
longer counts; it does not waive the required completion.

Hosted security review is optional. Its absence, quota exhaustion, pending
request, running/failed state or stale security result does not prevent code
review from satisfying the gate. Recognized security rows and metadata are
advisory, never evidence that code review completed. Do not describe an absent
or unsuccessful security review as passed. The former `require-hosted-review`
label and security-quota exception comments have no policy effect; adding or
removing labels cannot waive code review. No quota receipt is necessary.

Security-sensitive changes (including authentication, authorization, isolation,
untrusted input, secrets, publication, CI permissions and deployment boundaries)
still need a focused security assessment in the PR: affected boundary, relevant
abuse cases, mitigation and regression evidence. Fix actual findings or record
a reasoned maintainer disposition before acceptance, including findings from
optional security review. Every review thread must be resolved, and the existing
full-head maintainer acceptance must postdate every inline comment/reply,
including edits. That privileged acceptance records substantive reconciliation
of all thread content; clicking Resolve is not reconciliation authorization.
New or edited priority-tagged official bot findings in issue comments and review
bodies also require renewed acceptance. Every thread, reply and review page must
be available; missing or incomplete evidence leaves the gate blocked. The
maintainer checks disclosure and synthetic-data provenance too.

Request `@codex review` deliberately after implementation and validation. No
repository workflow posts review commands on open or synchronize. Keep automatic
code review disabled in the Codex integration's repository settings; this policy
does not change that separate setting. After reconciling discussions, dispatch
the Hosted review gate with the PR number if another evaluation is needed.

The required status and native approval remain PR-specific in effect: a shared
commit status cannot grant another PR native approval. The gate withdraws its
prior approval before reevaluation, checks head and base before and after
approval, and withdraws approval if either changes. Keep strict up-to-date
protection: a default-branch advance requires an updated head, fresh CI and fresh
hosted code review. Existing native protections and Quality, publication and
Gitleaks checks remain mandatory. The gate uses pull-request write permission,
not repository-admin dismissal rights.

Review and review-comment Actions events execute the PR merge-ref workflow.
A same-repository PR can change that workflow's permissions: a no-op relay with
`permissions: {}` is not a trusted boundary. There is no review-event relay or
`workflow_run` consumer. Only `pull_request_target`, issue comments and explicit
manual dispatch invoke this gate; see GitHub's
[Actions event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
Manual dispatch must select the default branch, never a candidate branch. The
job also rejects non-default-branch dispatches, but a guard in editable candidate
YAML cannot make dispatching that candidate safe.

Use explicit trusted revalidation: keep the PR draft while review and findings
are changing; after completion and reconciliation, post the full-head acceptance
below or dispatch **Hosted review gate** from the default branch with the PR
number. Inspect that fresh run and current review evidence before a manual
merge. Do not use auto-merge with this protocol. After any review submission,
edit, dismissal, inline-comment mutation or resolution change, repeat
revalidation and renew acceptance when content changed. Review-surface changes
do not automatically invalidate an existing green status. This is a maintainer
procedure, not an atomic merge barrier or complete automated enforcement of
post-run mutations. If that guarantee is required, remain blocked until a
separately reviewed trusted event integration is available; this PR grants no
settings, token or webhook-service changes.

Thread resolution/unresolution is a
[webhook event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review_thread),
not a supported Actions trigger. No workflow claims to receive it, and polling
would not close the merge window. The gate therefore does not authorize
reconciliation from the mutable `resolvedBy` actor. It uses the existing
privileged full-head acceptance after all inline content instead. A contributor
cannot authorize reconciliation by resolving a thread; toggling an already
accepted thread does not erase its maintainer reconciliation. Native required
conversation resolution blocks while the thread is unresolved. New or edited
comments invalidate the acceptance cutoff on the next explicit revalidation;
acceptance edits/deletion use the existing issue-comment events.
Inline freshness uses the latest valid creation, publication and body-edit
timestamp, not the generic metadata-update timestamp; review submission time is
also included. These fields describe different events, and the
[GitHub schema](https://docs.github.com/en/graphql/reference/pulls#pullrequestreviewcomment)
does not guarantee their ordering. Publication before creation is accepted, but
cannot lower freshness below creation or any newer edit/submission. Missing
required fields and malformed or timezone-free timestamps still fail closed.
If a gate run saw an unresolved thread, resolve it and dispatch the gate or post
fresh acceptance to reevaluate. Keep native conversation protection enabled;
this division of responsibility requires it. No webhook service, extra token
permissions or additional acceptance ceremony is introduced.

The gate reads trusted default-branch code and GitHub metadata only; it never executes the PR head
with a write token. External contributor workflows require
maintainer approval. Use hosted runners with synthetic fixtures; do not attach
private infrastructure or deployment credentials to public Actions. Default
workflow permissions are read-only and actions are pinned to full commits.
Enable GitHub Actions PR-review approval capability for this trusted workflow;
only this gate requests pull-request write permission.

After hosted code review completes, a maintainer independently inspects the
full current head, the focused security assessment where applicable, and all
findings/dispositions, then posts the existing exact one-line PR comment with
the full 40-character commit ID:

```text
RecordBench maintainer acceptance: FULL_COMMIT_ID
```

For a clean result with no native CODE review, add one line to that same comment:

```text
RecordBench maintainer acceptance: FULL_COMMIT_ID
CODE verification: request REQUEST_COMMENT_ID; result RESULT_COMMENT_ID; observed-unchanged-head
```

Use `execution-context` instead of `observed-unchanged-head` only when the
accepting maintainer or authorized merging agent actually inspected the hosted
review execution context and verified its complete commit ID. Otherwise observe
the full PR head from the explicit request through completion and verify it did
not change (including a change away and back). Checking the head only at the two
endpoints or resolving the short SHA is not enough. If the execution context or
unchanged-head observation cannot establish the binding, request a fresh review
on a stable head and observe it; do not attest retrospectively from a prefix.
The request must name the complete head and remain unedited. Reference the
specific unedited official clean CODE result comment, not the mutable summary,
a reaction, SECURITY result or another PR's comment. The gate also requires the
latest completed CODE summary and fresh findings disposition.

This line explicitly attests: “I verified that this actual hosted CODE review
reviewed this complete commit.” It is an accountable maintainer trust decision,
not machine proof of execution. It is not a quota or review waiver. The merging
agent can perform and record this verification within its existing authority;
no separate human ceremony is required. Never post it without the observation
or execution-context evidence it asserts.

Acceptance must be strictly later than code completion, every inline comment or
reply (including edits), and priority-tagged official bot findings in issue
comments and review bodies, from an account with current write, maintain or admin
permission. Ordinary acceptance reconciles findings; only the explicit verification line
adds the trusted clean-review binding. A changed head, newer
code completion or removed acceptance requires renewed acceptance. Missing
acceptance leaves the gate pending. Current access is verified through GitHub,
not the comment's displayed association. Security credit availability does not
add a separate acceptance or exception step.

### Diagnosing gate execution failures

A normal missing-review or missing-acceptance result leaves the gate pending.
Findings without a later maintainer acceptance also leave it pending; unresolved
review discussions produce a failed policy status. These are distinct from an
execution exception, which exits nonzero and issues no new passing status. An
early exception, before the pending status is published, can preserve an older
successful status for the same head. Its log reports only a fixed `stage` and an
allowlisted `exception_class`. API transport,
GraphQL response validation, thread/review normalization, permission checks and
policy evaluation have separate stages. Unknown exception types are reported as
`Exception`; no exception message, response body, request URL, token or traceback
is printed. Preserve fail-closed behavior while investigating; never substitute
manual status publication or a label for successful evaluation.

Explicit finding-normalization rejections also report an allowlisted `reason`
with `exception_class: NormalizationError`: `body-type`, `created-type`,
`published-type`, `edited-type`, or `submitted-type`. An unrecognized reason
is `unknown`. These distinguish the rejected field/type without
printing any field value, content, identifier or timestamp. Missing fields and
timestamp parse errors retain their bounded exception-class diagnostics.
Historical `published-before-created`, `edited-before-created` and
`submitted-before-created` reasons came from an unsupported ordering assumption.
Normalization now considers all valid timestamps and requires acceptance after
their maximum, rather than rejecting a differing order.

These diagnostics do not establish or repair the cause of an earlier failure
whose exception was suppressed. Reproduce that failure in trusted default-branch
execution to obtain the bounded diagnostic before choosing a repair.

### Historical security-quota policy

The former security-quota exception landed in
[#71](https://github.com/neilofneils404/recordbench-oss/pull/71) at
`17eafce965062e9fbdf8884738e277573abc8f7f` using the immutable protected tag
`recordbench-quota-policy-bootstrap-20260912-v1`. Historical receipts retain
that meaning; new PRs use mandatory code review and optional hosted security
review. Retain the historical tag and its update/deletion protection without
bypass actors. The scoped bootstrap dispatch remains removed. This policy is
executed only after normal review and landing on the trusted default branch;
a PR's candidate workflow cannot self-activate it.

The gate withdraws its prior native approval when a PR moves away from the
default branch. Publication identity dispositions support SHA-1 and SHA-256
repository object IDs.
