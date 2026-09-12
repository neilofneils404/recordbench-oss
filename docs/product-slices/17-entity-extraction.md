# 17: Improve entity discovery and reviewer-controlled reconciliation

Status: active. Slice 16 landed in #77. Storage/behavior contract: #78.

## Finding and outcome

Current patterns look for titled people, capitalized places after selected
prepositions, and a limited set of date formats. Notebook suggestions stop at
75 new items by default or 2,500 scanned units. They do not provide broad
people/organization/object discovery or a complete set of mentions.

## Small implementation

Run entity extraction incrementally over the durable unit coverage from 12,
saving all supported mentions rather than only new normalized labels. First
support untitled people, organizations, and explicit identifiers/objects on a
bounded synthetic corpus. Store extractor version, source support, and review
status. Keep failed/unprocessed units visible.

Add reviewer-confirmed alias links and merge/split with undo. Machine matching
proposes candidates; shared names, similar spellings, or transcript speaker
clusters do not establish identity. Preserve distinct mentions when rejecting
or reversing a suggested merge. Date normalization needs ambiguity and timezone
fields, not a guessed single timestamp.

## Code and acceptance

Build on entity/mention storage from 16 and existing source unit/analysis jobs.
Keep the extractor behind a replaceable interface; retain simple deterministic
identifier extraction where appropriate. A new learned model requires pinned
revision, licensing, offline readiness, and evaluation before adoption.

Measure mention recall and false merges for untitled names, aliases, same-name
people, multilingual/OCR variation, and more than 75 entities. Verify resume,
source replacement, review corrections surviving re-extraction, and merge/split
undo. Persistence changes need migration and clean-restore evidence.

## Implementation contract

See [entity discovery](../ENTITY_DISCOVERY.md) for the implemented processing,
reviewer decisions, deterministic recognition limits and recovery contract.
This slice remains active until its ready PR passes final-head hosted review
and a separate maintainer decision lands it.
