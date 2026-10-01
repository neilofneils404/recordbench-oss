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
history. New commits and merges must use the maintainer's validated GitHub
no-reply attribution; this exception does not authorize later personal-address
attribution.

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
incomplete code-review summary formats fail closed. Changed heads and newer or
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

Review submission/edit/dismissal and inline-comment creation/edit/deletion
also trigger automatic revalidation. The `Hosted review events` relay has no
token permissions, checkout, artifacts or PR-code execution. Its requested and
completed runs wake the default-branch gate regardless of success; reruns are
covered by completion. Only the trusted gate selects PR numbers, rereads live
head/base and findings, and withdraws or renews its native approval. Run outcomes
and event head/base snapshots never authorize approval. If GitHub omits PR
associations, the gate reevaluates all open default-branch PRs. All event paths
share per-PR serialization. No additional token permissions are granted.

GitHub executes review-event workflows on the PR merge ref, while `workflow_run`
uses the default branch; see the
[official Actions event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).
Keep these workflows separate. Do not add review-event triggers directly to the
privileged gate or consume relay artifacts. Revalidation remains asynchronous;
Actions scheduling is not an atomic merge barrier.

Thread resolution/unresolution is a
[webhook event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request_review_thread),
not a supported Actions trigger. No workflow claims to receive it, and polling
would not close the merge window. The gate therefore does not authorize
reconciliation from the mutable `resolvedBy` actor. It uses the existing
privileged full-head acceptance after all inline content instead. A contributor
cannot authorize reconciliation by resolving a thread; toggling an already
accepted thread does not erase its maintainer reconciliation. Native required
conversation resolution blocks while the thread is unresolved. New or edited
comments invalidate the acceptance cutoff through supported review/comment
events, and acceptance edits/deletion use the existing issue-comment events.
Inline freshness uses creation, publication and body-edit timestamps, not the
generic metadata-update timestamp; review submission time is also included.
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

Acceptance must be strictly later than code completion, every inline comment or
reply (including edits), and priority-tagged official bot findings in issue
comments and review bodies, from an account with current write, maintain or admin
permission. This binds the bot's abbreviated code SHA to the full head; a prefix match alone is insufficient. A changed head, newer
code completion or removed acceptance requires renewed acceptance. Missing
acceptance leaves the gate pending. Current access is verified through GitHub,
not the comment's displayed association. Security credit availability does not
add a separate acceptance or exception step.

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
