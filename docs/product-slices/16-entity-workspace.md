# 16: Make People, Places, and Things a first-class workspace

Status: implementation under review. See [entity workspace](../ENTITY_WORKSPACE.md)
for the manual workflow, storage contract, recovery commands and limits.
The cruise remains Next until this implementation lands.

## Finding and outcome

Reference candidates are stored as notebook suggestions. The review map is
under Work product and links people/places back to notes. Suggestion deduplication
uses a normalized label and retains the first reference from a scan, rather
than building a complete mention index. A person is more than a note title.

## Small implementation

Introduce entity and mention records with stable matter-scoped identities.
An entity has a type, display name, review status, and aliases; every mention
retains exact source/version/location support. Start with people, places, and
things and manual creation plus import of existing supported suggestions.

Add a visible matter navigation entry and an entity detail page listing its
mentions and linked source passages. Keep notes attached as commentary.
Import existing notes non-destructively: preserve originals, references, and
correction history. Do not merge different people solely because names match.
Automated richer extraction and relationships are separate slices.

## Code and acceptance

Start with `suggest_notebook_references`, notebook data in `workspace_store.py`,
`matter_analysis.py`, matter navigation, and `workbench_analysis.html`.

Tests cover repeated mentions, identical names belonging to different people,
manual entity creation, stale source references, cross-matter denial, and old
notes remaining usable. Browser acceptance opens an entity and navigates to all
its supported mentions. Introduce mirrored migrations with backup/clean-restore
and rollback evidence. Do not replace the underlying notes store through a
navigation-only refactor.
