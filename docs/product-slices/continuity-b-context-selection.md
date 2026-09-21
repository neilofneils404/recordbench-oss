# Continuity B — explicit durable context selection

Status: **Implementing; acceptance and landing pending.** The existing
[cruise](../EXIT_ALPHA_CRUISE.md) is the binding queue. C is not selected.

Reviewed baseline: `0d59d5fe4f7be575a66039274415de945a6d5db5`.
Implementation base: `91a97d2ef2b7d4733551a9189bd9c2c7c50c692c`.
The newer commit corrects test lease timing and documents that correction; it is
preserved. The original checkout predates A and has unrelated onboarding edits;
those remain untouched in that checkout. This increment uses an isolated branch.
The companion B/C proposal informs this contract; only the user's B scope is
selected, not its C instructions or model evaluation.

## Selected contract

One empty-by-default selection per matter and reviewer. Knowledge stays shared;
selection ownership is neither private notes nor a team default. Typed stable
references identify notes, entities and assertions (including events), including
all existing review statuses and origins. Selection never confirms truth.
Persist ordered references, approval stamps, selection revisions and attribution,
not copies of current facts. Note versions are opaque updated_at tokens; entity
and assertion versions are actual revisions. Support and role dependencies are
tracked separately. No truncated A projection is used as authoritative context.

GET and preview do not write selections or knowledge. Mutations use the existing
source guard, authorized connection and transaction, CSRF and current authority.
Concurrent changes require explicit recovery. Missing records stay missing;
changed records require explicit reapproval. Remove/reorder never refresh other
approvals. No same-name merge, record recreation or automatic re-add.

Fifty references is a storage/UI limit, not a model-fit promise. Bound reference
scans and serialized bytes before loading full records. Complete exports include
attributed selection manifests; note-only exports and historical answer scopes
are unchanged. Add a paired migration, stopped-backup/clean-restore and purge
coverage. Mixed-version writers are unsupported; stop writers before upgrade,
retain a complete pre-upgrade backup and use its matching release for rollback.
Ordinary exports are not restore archives.

No model calls, prompt/retrieval changes, jobs, Report-memory compilation,
infrastructure changes or lifecycle reopening. Saved selections are **not yet
consumed by answers**. B acceptance requires synthetic service, HTTP and existing
browser-runner evidence, restart, migration/restore/export/purge, current Quality
and publication checks. Required landing remains pending until separately
authorized. Exact executed evidence and handoff will be appended here.

## Executed evidence — first persistence increment

Python 3.12, synthetic fixtures, `PYTHONPATH=src` with the existing contributor
environment. `python -m pytest -q tests/test_matter_context.py
tests/test_matter_knowledge_workflow.py`: **45 passed**. Covers all review states,
two owners, same-name identities, away-and-back note edits, role/source changes,
concurrent revisions, bounded materialization, missing/removal behavior,
SQLite backup/clean restore/restart/export/purge, and unchanged A workflows.
`python scripts/publication-check.py --skip-history`: generic working tree
**CLEAN**; history was not scanned. Initial development tests exposed a missing
migration registration and fixture argument errors; these were corrected before
the passing run. HTTP/export/browser and full gates are still in progress.
