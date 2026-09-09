# Exact document search

The matter's **Find sources** route enumerates documents using
`recordbench-exact-v1`. The existing **Semantic passage search** continues to
select ranked passages for discovery and answering; its candidate limit does
not constrain exact results. Exact search requires no embedding service,
reranker, model, or PostgreSQL retrieval index.

The default form asks for names, places, or details. Optional refinements let
reviewers include an exact phrase, leave out words, and choose a collection or
saved source set. These fields treat words literally, including words such as
"and"; reviewers do not need Boolean syntax. A separate collapsed **Advanced
search** form accepts the grammar directly. Results lead with source names,
original-text excerpts with safely escaped highlights, page/section links,
and an **Open source** action. Counts and preparation gaps use plain language.

## Current behavior

The route authorizes the matter before reading its population. Collection and
source-set filters intersect, including an empty intersection. Unknown and
foreign scopes fail closed. Matching and counting use only this scoped
population. Ready sources with searchable text are eligible; not-ready and
empty-text sources appear as separate exclusion counts. A source load failure
invalidates the scan rather than becoming a nonmatch.

AND, OR, and NOT apply across all extracted units of one document. For example,
`red AND bicycle NOT blue` rejects a document with `blue` on its final page,
even if the other words occur earlier. Phrases require consecutive normalized
tokens within one unit. The [grammar contract](EXACT_SEARCH.md) defines
normalization, punctuation, limits, and unsupported syntax.

Totals count documents after the whole population is evaluated. Sorting uses
case-folded source name and document ID; pages contain 25, 50, or 100 documents.
More than 100 matches remain browsable. Up to three units containing positive
query terms explain each result, with visibly shortened text previews. These
preview limits never limit matching or document membership. Negation-only
matches explain that the requested terms were absent. Source links use the
current version's existing source-review token.

Pagination links carry a fingerprint of the grammar, original/parsed query,
matter and selected scopes, source membership, names, states, versions, and
extracted text. Each page reruns the bounded scan. Any change produces HTTP 409
and asks the user to rerun; no stale page or silently mixed result population
is returned. This detects change between requests, not after a response is sent.
The result is a live view, not a frozen receipt. No save-result action or new
storage schema is introduced.

## Backend and operating contract

`ExactSearchBackend` is separate from hybrid answer retrieval. The initial
`ReferenceExactSearchBackend` reads authoritative extracted units in either a
CPU-only or PostgreSQL-configured deployment. It never delegates exact
membership to PostgreSQL web-search syntax or a top-k candidate list.

`ExactScanPolicy` is injectable product policy, independent of development-host
hardware. Defaults are 10,000 scoped documents, 10 million extracted characters,
and a five-second cooperative processing deadline. Deadline checks run between
sources, within tokenization, and within phrase evaluation. Exhaustion produces
HTTP 503 with **no exact total or partial results** and guidance to select a
smaller scope. The time budget is cooperative: source-file I/O, JSON loading,
Unicode normalization, and lock acquisition are not preempted. This is not a
hard wall-clock service guarantee. A scan holds the matter's source mutation
lock and workspace lock for consistent scope and source state; it can delay
other workspace operations until it returns.

This initial adapter deliberately rescans each page. It is not the scalable
indexed backend. A production-scale adapter should use a consistent database
snapshot or versioned result cache, stable keyset pagination, cancellable query
execution, and index completeness/version checks. It must implement the same
grammar and document/unit boundaries, authorize and scope before counts, expose
unprocessed sources, and return all matches without semantic additions. Index
lag cannot silently turn into zero matches. Cache keys must include actor
authorization, matter, scope, grammar, query, and source versions; authorization
must be rechecked on each read. Persisting a frozen receipt later requires its
query, grammar/plan, scope, source versions and membership, plus schema migration
and backup/restore evidence. Those capabilities remain unbuilt.

## Validation and limits

Synthetic tests run the frozen known-answer corpus through the result service,
enumerate 137 matches with stable pagination, cover different-page NOT and phrase
boundaries, exclusions, invalid syntax, scope intersections, foreign-matter
canaries, source mutations, and budget/read failures. The route test forbids
calling the ranked retriever. Plain-form tests cover literal operator words,
include/phrase/exclude combinations, filter intersections, retained pagination
inputs, empty-input guidance, and original-text previews. Browser checks cover
the first-use form, a successful search, no-result guidance, keyboard submission
with visible focus, and a 390-pixel viewport without horizontal overflow.
The shared grammar's truth tables remain required.

Real PostgreSQL indexed exact-search acceptance is pending; no PostgreSQL
exact adapter is claimed. The same authoritative scan is used when a PostgreSQL
answer backend is configured. Large-population latency, concurrent-user load,
and persisted-search restore acceptance require the future adapter and separate
evidence. No deployment or confidential-workload acceptance is implied.
