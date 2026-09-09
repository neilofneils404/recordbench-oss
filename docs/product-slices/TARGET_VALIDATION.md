# Validate the unmerged integration candidate

The target Linux machine can test this work before any pull request is merged.
The `codex/portable-candidate-20260909` branch is the combined test surface
for the repaired component revisions. It replaces the older September 8
integration snapshot; use the new manifest and full commit from its handoff.
Use a separate OSS checkout of the integration branch and a separate synthetic
installation. The branch is a review/test candidate, not an accepted release.
Its component PRs remain independently reviewable.

## Fetch the exact candidate

Use the full commit ID in the maintainer's handoff. The branch name is convenient
for discovery; the full commit identifies what was actually tested.

```bash
git clone --single-branch --branch codex/portable-candidate-20260909 \
  https://github.com/neilofneils404/recordbench-oss.git recordbench-validation
cd recordbench-validation
git checkout --detach FULL_COMMIT_FROM_HANDOFF
git rev-parse HEAD
git status --short
```

Both commands at the end should confirm the expected commit and a clean tree.
No merge, default-branch update, or existing deployment change is required.
Keep private deployment overlays and existing runtime state outside this checkout.
Use synthetic sources throughout this acceptance run. If a defect occurs in a
private deployment later, report a content-free behavioral description and a
synthetic reproduction through the normal upstream process.

The [component manifest](integration-components.json) beside this document records the PR revisions used to
assemble the candidate. A later component correction produces a new integration
commit and a new test receipt; a previous receipt does not cover changed code.

## First check: portable code on Linux

Follow [contributor setup](../../CONTRIBUTING.md#set-up-a-development-checkout),
including the documented system dependencies, then run:

```bash
make bootstrap
make check
```

Record the exact candidate, command exit statuses, and failed synthetic test
names. Keep raw local logs outside Git. A full test pass is useful Linux evidence;
it does not demonstrate that the intended GPU/model and deployment profile work.
If a synthetic upload test is blocked only by the configured disk reserve, record
that separately. A test-only reserve override is not a passing installation
preflight or a reason to weaken the deployed safety reserve.

## Second check: the intended application profile

Follow [installation](../INSTALL.md) as the dedicated non-root account. Start with
`./install preflight` for the actual model profile, dedicated validation root,
separate storage, and chosen loopback port. Keep its JSON result locally. Resolve
blocking prerequisites before installation; do not infer GPU readiness from a
CPU test or from another machine's receipt.

Install the candidate into that separate validation root. The installer stages
the source from the checkout; it does not require a merge into `main`. Use the
existing pinned model revision and offline staging/verification procedure. Run
`./install doctor` against the validation root after launch.

Exercise these workflows with a small synthetic matter:

1. First login, setup handoff, source preparation, and actual readiness.
2. Create a second local reviewer when the local-account profile is enabled;
   grant only intended matter access, then test password-reset and disable
   revocation from an already signed-in second session. Verify another matter
   remains unavailable to that reviewer.
3. Find sources using words, a phrase, exclusions, and available nearby-word
   controls. Compare every result and displayed total to a known fixture, follow
   source links, and check more than one result page.
4. Run the existing selected-passage investigation and inspect its recorded
   budget/coverage. Run all-extracted-text
   review on a fixture with a decisive late passage, an extraction failure,
   a long unit, and a conflicting account. Check the durable unit ledger,
   cancellation/restart, source-change rejection, and honest incomplete states.
5. Compile a timeline, people/places/things report, and focused topic brief from
   saved AI work and human notes. Check relevance, contradictions, source links,
   unavailable evidence, and coverage. Edit and reorder the draft; verify Word
   and Markdown preserve the human edit and its source/review basis.
6. Repeat key workflows with the real pinned local model offline. Record
   incorrect or unsupported findings as failures needing investigation; the
   deterministic source-echo browser tests are workflow tests only.
7. With long conversations and case-note lists, independently scroll the matter
   rail, saved-conversation menu, and note tools. Check keyboard reachability,
   consistent page alignment, and narrow-screen layouts.
8. Run the documented encrypted backup and restore into a clean validation
   destination. Check accounts, source versions, reports, and queued-work
   recovery. Exercise an update and the documented rollback procedure using
   synthetic state, preserving both old and candidate revision identities.

Use the relevant browser acceptance scripts and release/runbooks alongside this
walkthrough. Existing auth and media profiles remain separate acceptance lanes;
only mark a lane passed when that profile was actually exercised.

## Record an acceptance decision

Copy the [receipt template](TARGET_VALIDATION_RECEIPT.md) outside the checkout.
For each lane, record **passed**, **failed**, or **not run**, plus the exact commit,
configured profile/model revision, synthetic fixture, and concise result. Keep
host identities, paths, credentials, and private deployment details outside the
public repository. Public follow-up PRs should contain only synthetic
reproductions and generalized corrections.

Source readiness and installed-target readiness are separate. Finish
code/security reviews and CI on the final PR heads, then obtain the full-commit
maintainer acceptance required by
[the public-alpha gate](../PUBLIC_ALPHA.md#merge-and-automation-boundary).
Target access is not needed to continue portable development or source review.
Target installation, model quality and recovery lanes stay not run until they are
actually exercised on the intended profile.

Use the component PRs as the default merge path. The combined candidate exists for
validation; any integration PR should be closed after its component changes land.
Do not merge both paths independently. Retarget follow-up PRs based on the integration
branch onto the accepted default branch after their prerequisites land, then
refresh their diff, checks, and reviews. Merge accepted component PRs in dependency order. Recheck the assembled tree and
required CI after conflict resolution or default-branch advances. Deployment
adoption is a later explicit step against the accepted revision; testing this
branch alone does not update or validate an existing deployment.

## Adoption boundaries in this candidate

Read [team setup adoption and recovery](../TEAM_SETUP_ADOPTION.md) before
changing account format or mounts. Report migrations require the pre-upgrade
backup and matching application for rollback; see [storage and backup](../STORAGE_AND_BACKUP.md).
Full-text screening has durable resource limits and unresolved extraction states;
read [full-text review](../FULL_TEXT_REVIEW.md) before treating a completed run
as evidence of coverage. Reports preserve the selected saved work within their
bounds; a report is not the complete full-text range ledger.
