# September 2026 portable workflow adoption record

This record describes the portable OSS changes assembled from PRs #51–#58 in
PR #59. The [component manifest](integration-components.json) pins every source
revision and dependency. Obtain the complete accepted integration commit and
its source-validation results from the PR and maintainer handoff. A branch
name, this document, or a successful source test is not target acceptance.

## Source acceptance and the batch exception

The maintainer authorized completing this OSS merge batch without GitHub Codex
security reviews because security-review credits are unavailable. This is an
explicit waiver, not a completed or passing security review. It applies only to
this batch; the repository's ordinary review policy remains unchanged.
Completed current-head code reviews, reconciled findings, required application,
transcription, deployment-contract and secret-scan CI, publication inspection,
and full-commit maintainer acceptance remain required.

The existing hosted gate cannot represent this exception and will continue to
report pending. The maintainer merge record must identify the exact accepted
commit, the waived security review, the independently verified remaining checks,
and any temporary administrative bypass. Restore the original branch protection
immediately after that operation and verify its settings and the new main head.
Never label the pending hosted gate as passed or change the scanner's result.

For this batch, use the reviewed integration tree as the single path into main,
preserving the component commit histories. Reconcile the component and replaced
PRs with that integration; do not merge another copy of the same features.
Subsequent changes use ordinary PRs based on the accepted main revision.

## Product changes and dependencies

| Component | Reviewer or operator outcome | Dependency and adoption notes |
| --- | --- | --- |
| #51 Report compiler | Selected human work and source qualifications survive bounded compilation. | Pure compiler foundation; no schema or deployment changes in this component. |
| #52 Navigation | Matters, conversations and note tools remain reachable beside long content. | UI behavior; no migration. |
| #53 Find sources | Complete eligible-source scans, exclusions and proximity evidence with stable pages and source links. Corrupt or incomplete projections cannot produce misleading exact totals. | Bounded scan adapter; no search-index migration. Indexed large-population execution remains future work. |
| #54 Installer | Prerequisite checks, protected storage paths and faithful configuration inputs. | Correct newly reported environment failures before installation or update; do not replace retained state to bypass preflight. |
| #55 Account lifecycle | Account changes reach running sessions; password, role and enabled-state changes invalidate prior access. | Version 1 remains readable; mutations require explicit version 2 migration and recovery preparation. |
| #56 Reports | Timeline, people/places/things and topic drafts compile saved work, retain review/source basis, support editing and export, and recover deleted/cancelled requests. | Depends on #51; additive Report migrations 0027 and 0029. |
| #57 People and Team setup | Opt-in browser administration, current setup progress and resumable installation using canonical saved configuration. | Depends on #54 and #55; dedicated account directory/mounts and explicit stopped-writer migration or relocation where applicable. |
| #58 All extracted text | Durable bounded source/unit/range coverage, honest extraction gaps, cancellation/retry, complete ledger download and supported Report summaries. | Depends on #56; additive full-text migrations 0028 and 0030. |

The Python dependency declarations and pinned model revisions are unchanged by
this batch. Compiler and model-receipt versions have changed as documented in
their component runbooks; an old receipt or saved generated result is not proof
that a new request or cached model inventory has been validated.

## Configuration, compatibility and migrations

Preserve the existing identity provider, dedicated service account, network bind,
hostname, storage layout, selected model profile and protected credentials.
Resume uses canonical saved configuration; replacement command-line values must
not silently reconfigure an existing installation. Follow [installation](../INSTALL.md)
and [team setup adoption](../TEAM_SETUP_ADOPTION.md).

Browser account management is explicitly enabled for the local-account profile.
It requires a dedicated owner-only account directory, the matching Compose
overlay and a version-2 store. The general secrets mount remains read-only.
Use the stopped-writer migration, relocation and rollback procedures in
[account lifecycle](../LOCAL_ACCOUNT_LIFECYCLE.md) and
[browser account management](../LOCAL_ACCOUNT_BROWSER.md). Expect fresh sign-in
where account revisions or the session recovery boundary change. Restoring old
account bytes alone must not revive previously issued local sessions.

Take a consistent pre-upgrade backup before applying the additive Report and
full-text schemas. The old application is not a supported reader of an upgraded
database. A rollback pairs the previous application/configuration with the
matching clean pre-upgrade restore; it is not merely a code checkout or a
reverse schema edit. Later work absent from that backup requires deliberate
reconciliation. See [storage and backup](../STORAGE_AND_BACKUP.md).

Existing selected-passage review remains available. All-extracted-text completion
means recorded extracted-range processing within the frozen resource limits;
it does not establish that every relevant fact was recognized. Missing extraction,
failed or invalidated ranges remain visible. Reports copy bounded saved-work
summaries, not the entire range ledger. Keep the original ledger where complete
range outcomes are needed. See [full-text review](../FULL_TEXT_REVIEW.md) and
[Report compilation](../REPORT_COMPILATION.md).

## Validation and deferred deployment acceptance

The public PR records source tests, Linux CI, synthetic browser workflows,
publication inspection and synthetic backup/clean-restore evidence by exact
revision. Native Mac platform exceptions are listed separately from passing
Linux CI. Deterministic source-echo browser clients validate workflow behavior;
they do not qualify model relevance, recall or factual reliability.

Server installation, intended-profile GPU capacity, pinned local-model quality,
offline operation, encrypted target backup/clean restore and target rollback are
deferred. No installed node, model selection or deployment configuration is
changed by this OSS merge. When the target is available, follow the
[validation walkthrough](TARGET_VALIDATION.md) and copy its
[receipt template](TARGET_VALIDATION_RECEIPT.md) outside public Git. Record each
lane as passed, failed or not run, tied to the exact accepted upstream commit.

Keep downstream configuration and recovery locations in a separate private
adoption record. That record should capture the old and new upstream revisions,
local differences, configuration decisions, migrations, observed validation,
recovery boundary and promotion decision. Bring defects upstream as synthetic
reproductions and content-free behavior descriptions.
