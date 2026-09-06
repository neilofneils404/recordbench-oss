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
git config --local core.hooksPath .githooks
```

If the scanner dependencies are in a virtual environment, set
`recordbench.publicationPython` to its absolute Python executable path using
`git config --local`. The default is `python3`.

The hook scans every outgoing branch/tag and its reachable history in an
isolated temporary repository before Git transmits objects. Install `pypdf`
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

Protect main with required CI, resolved discussions, and no force pushes or
deletion. `hosted-review-gate` requires completed GitHub Codex code and security
reviews on the current head and resolved review discussions. Request renewed
reviews after corrections; never use a previous commit's review as acceptance.
If a discussion was reconciled after the last summary update, dispatch the
Hosted review gate workflow with the PR number to recheck it. A changed Codex
summary format blocks pending diagnosis rather than silently passing.

The gate reads trusted default-branch code and GitHub metadata only; it never
executes the PR head with a write token. External contributor workflows require
maintainer approval. Use hosted runners with synthetic fixtures; do not attach
private infrastructure or deployment credentials to public Actions. Default
workflow permissions are read-only and actions are pinned to full commits.

The maintainer still reviews disclosure, provenance, and reconciled findings.
Outside contributors do not need or receive access to a private deployment.
