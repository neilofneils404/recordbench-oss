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
the underlying check. Public author identities are deliberate and use GitHub
no-reply email addresses. Keep the private audit and its deny terms outside Git.

Source publication does not ship a production image or promise installation,
hardware, recovery, legal accuracy, completeness, or confidential-workload
acceptance. The full supported-release requirements remain in
[release readiness](RELEASE_READINESS.md). Optional dependencies and models
have separate upstream terms; see [third-party notices](../THIRD_PARTY_NOTICES.md).

## Prevent disclosure before publishing

CI runs after content reaches GitHub. It cannot prevent an initial disclosure.
Install the local pre-push check in every publishing checkout:

```console
python3 scripts/install-publication-hook.py ~/.local/share/recordbench-publication-guard/reviewed-v1
```

Run the installer from a trusted, reviewed checkout with the Python environment
that contains the scanner dependencies. Both that environment and the new
installation directory must be outside the publishing checkout. The installer
copies the reviewed scanner and hook, pins the interpreter, and enables isolated
Python execution. Branch switches cannot replace this installed code. Reinstall
reviewed updates into a new directory. Do not point `core.hooksPath` at the
branch-owned `.githooks` directory.

The hook scans every outgoing branch/tag and its reachable history in an
isolated temporary repository before Git transmits objects, including every
reachable annotated tag object. CI also runs on tag pushes. Install `pypdf`
and `ffprobe` as described in the publication checklist; missing inspection
dependencies block publication. A removed file still exists in history and
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

Protect the default branch with required CI, `hosted-review-gate`, resolved
discussions, at least one native PR approval, stale-approval dismissal, approval
of the most recent push, and no force pushes or deletion. `hosted-review-gate` requires completed GitHub Codex code and security
reviews on the current head and review discussions reconciled by someone with
repository write, maintain or admin access. An outside author cannot satisfy the
gate by resolving their own findings. Request renewed
reviews after corrections; never use a previous commit's review as acceptance.
If a discussion was reconciled after the last summary update, dispatch the
Hosted review gate workflow with the PR number to recheck it. A changed Codex
summary format blocks pending diagnosis rather than silently passing. Edited
requests invalidate earlier completions; each request is compared with its own
code or security review completion.

A passing gate also submits a native approval to the individual PR, bound to
its full head and recorded base. Both that native approval and the status are
required: a shared commit status alone cannot authorize another PR with the
same head. The gate only approves PRs targeting the default branch. It withdraws
its earlier native approval with a review requesting revalidation before
reevaluation, and rechecks both head and base around approval. A change during
approval also withdraws the newly issued approval. This uses pull-request write
permission; the workflow does not need repository-admin review-dismissal rights.
Native approvals must not be disabled while relying on this gate. Separate
branches need their own deliberate protection policy.

The gate reads trusted default-branch code and GitHub metadata only; it never
executes the PR head with a write token. External contributor workflows require
maintainer approval. Use hosted runners with synthetic fixtures; do not attach
private infrastructure or deployment credentials to public Actions. Default
workflow permissions are read-only and actions are pinned to full commits.
Enable GitHub Actions PR-review approval capability for this trusted workflow;
only this gate requests pull-request write permission.

After both hosted reviews finish, a maintainer independently checks the full
current head and review results, then posts this exact one-line PR comment,
replacing the placeholder with the complete 40-character commit ID:

```text
RecordBench maintainer acceptance: FULL_COMMIT_ID
```

The acceptance must follow both review completions and come from an account
with current write, maintain or admin permission. This additional full-commit
acceptance is required because the code-review summary abbreviates its commit
ID; a matching short prefix alone is not sufficient. A changed head, a newer
review completion, or removal of the acceptance requires renewed acceptance.
Missing acceptance leaves the gate pending. The gate verifies current access
through GitHub, rather than trusting the comment's displayed association.

The maintainer still reviews disclosure, provenance, and reconciled findings.
Outside contributors do not need or receive access to a private deployment.

The gate withdraws its prior native approval when a PR moves away from the
default branch. Publication identity dispositions support SHA-1 and SHA-256
repository object IDs.
