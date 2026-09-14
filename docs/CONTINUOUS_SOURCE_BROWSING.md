# Continuous source inspection

Opening a source from Sources keeps the current collection, source set, folder
subtree, filename/folder query, status, kind, review state, identical-byte filter,
sort and source page size beside the existing document or recording viewer.
Use **Browse collections, folders and filters** to change that view in the
existing catalog. The catalog's folder heading now describes this entry point;
there is no second folder hierarchy or organization model.

The source list stays beside the viewer on desktop and becomes a bounded,
scrollable region above it on narrow screens. The active source has an outline
and `aria-current="page"`. Tab reaches ordinary links; within the source list,
Up/Down and Home/End move focus without opening a source. Enter opens the focused
source. No global shortcuts intercept typing, player controls or document keys.

## Ordering and boundaries

The sequence uses exactly the library's five sorts: newest/oldest by added time,
name ascending/descending by normalized display name, and status by attention,
processing, then ready followed by name. Every sort breaks ties by document ID
(in the same direction as the primary sort). A display name may include its
relative path. Folder scopes include descendants and exclude prefix siblings.

Only 25, 50 or 100 source rows are rendered. A database rank locates the active
source's page, including when a bookmarked page number is stale; at a page edge,
the adjacent bounded page supplies the next or previous source. There is no wrap
at the first or last matching source. The catalog link returns to the active
source page and provides all page and folder controls. Direct links without a
library context use oldest-first matter order for compatibility.

The catalog is live, not a frozen review snapshot. Concurrent imports, moves,
removals or state changes can change position. A source outside the current
filters remains inspectable under normal authorization, with an explicit notice
and disabled sequence controls; the view never silently broadens its filters.
Mark reviewed and continue resolves the next matching source before marking the
current one, so an unreviewed filter remains useful. At the end it returns to the
same filtered library. Legacy callers without context retain the existing review
queue behavior.

## Integration contract and limits

`browse` on the source viewer is a URL-encoded library query, bounded to 8192
characters and an allowlist of library fields. It is not a return URL or an
authorization grant. Source and content routes still validate the matter and
source token; file serving, range requests, rendering and media processing remain
on their existing paths. Document passage navigation and transcript filtering and
paging and review-state buttons carry `browse` separately from viewer-local `unit`, `q` and `page`.

Search/nav labeling and discovery execution are separate work. Search and
entity/chronology entry points can pass this same context when they have a library
scope; they must keep citation locators separate and must not imply that the
filename filter is a full-text hit sequence. This slice does not persist context
in account preferences, auto-run discovery, or change ingestion. Other viewer
mutation actions (such as transcript correction and playback retry) retain their
existing return behavior and may reset browsing context.

This branch starts from main independently of intake PR #89. It does not copy
collection naming, picker, cancellation or browser-runner fixes. When integrating
both, retain both changes in shared templates, CSS, JavaScript and browser
acceptance scripts. No schema, model or deployment changes are required.

## Synthetic validation

`tests/test_continuous_source_browsing.py` exercises nested sibling exclusion,
duplicate names across 27 documents, all sort orders, both page crossings,
first/last boundaries, stale page relocation, filter retention, reviewed-state
changes, empty scopes, malformed context, foreign tokens, and media rendering
and byte ranges. Existing folder scale tests cover 10,000 sources.

The pinned `scripts/browser-accept-source-folders.py` journey checks actual folder
upload, consecutive document text, focus movement and Enter, previous/next,
return to filters, and desktop/narrow screenshots. It remains a separate journey
from the default intake/report runner; run it with the browser binaries verified
against `config/browser-testing.json`. All generated runtime state and screenshots
belong outside the repository.
