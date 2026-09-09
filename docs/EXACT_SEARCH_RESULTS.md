# Exact document search

The matter's **Find sources** route enumerates documents using
`recordbench-exact-v2`. The existing **Semantic passage search** continues to
select ranked passages for discovery and answering; its candidate limit does
not constrain exact results. Exact search requires no embedding service,
reranker, model, or PostgreSQL retrieval index.

The default form asks for names, places, or details. Optional refinements let
reviewers include an exact phrase, leave out words, and choose a collection or
saved source set. [Nearby-detail controls](EXACT_SEARCH_PROXIMITY.md) add two
words or phrases, a maximum count of intervening words, and either/first-before
order. These fields treat words literally, including words such as
"and"; reviewers do not need Boolean syntax. A separate collapsed **Advanced
search** form accepts the grammar directly. Results lead with source names,
original-text excerpts with safely escaped highlights, page/section links,
and an **Open source** action. Counts and preparation gaps use plain language.
Each search form preserves its own mode when submitted with Enter. Advanced
search has its own collection and source-set controls.

## Current behavior

The route authorizes the matter before reading its population. Collection and
source-set filters intersect, including an empty intersection. Unknown and
foreign scopes fail closed. Matching and counting use only this scoped
population. Ready sources with searchable text are eligible; not-ready and
empty-text sources appear as separate exclusion counts. PDFs with missing or
unverified page coverage are excluded entirely, including for negation queries,
and a visible warning says their incomplete pages were left out. Exact counts
apply only to the eligible fully covered extracted population. A blank extracted
page cannot be distinguished from a page needing OCR by this stored metadata;
the exclusion is deliberately conservative. A source load failure
invalidates the scan rather than becoming a nonmatch.

AND, OR, and NOT apply across all extracted units of one document. For example,
`red AND bicycle NOT blue` rejects a document with `blue` on its final page,
even if the other words occur earlier. Phrases require consecutive normalized
tokens within one unit. The [grammar contract](EXACT_SEARCH.md) defines
normalization, punctuation, limits, and unsupported syntax.

Totals count documents after the whole population is evaluated. Sorting uses
case-folded source name and document ID; pages contain 25, 50, or 100 documents.
More than 100 matches remain browsable. Up to three units containing positive
query terms from a satisfied Boolean proof explain each result, with visibly
shortened text previews. One supporting unit per positive part of that proof
is preferred before filling the display cap; a failed OR branch does not
supply misleading highlights. These
preview limits never limit matching or document membership. Phrase previews
anchor on complete consecutive-token phrase occurrences, preserving original
Unicode text. Page links use the position in the extracted-unit sequence, so
unreadable PDF pages do not shift the linked match. Negation-only
matches explain that the requested terms were absent. Source links use the
current version's existing source-review token. Transcript links carry the
matching timestamp and segment anchor instead of a text-unit page parameter.

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
128 million serialized input characters, 8 million serialized characters per
derived unit record, and a five-second cooperative processing deadline.
File-backed units stream through the [bounded reader](DERIVED_TEXT_READING.md):
input is charged after each bounded read, records are capped before JSON decode,
and decoded text is charged before retaining each unit. Oversized or unfinished
records fail the scan budget before decoding; a character limit reached partway
through a source stops without reading its remaining units. Deadline checks run
before and after reads and decoding, between sources, within tokenization,
within phrase evaluation, and through preview
generation for the displayed page. Previews are built inside the backend before
the result is returned; budget exhaustion there also suppresses the entire result. Exhaustion produces
HTTP 503 with **no exact total or partial results** and guidance to select a
smaller scope. The time budget is cooperative: one bounded source-file read or
record decode, Unicode normalization, and lock acquisition are not preempted. This is not a
hard wall-clock service guarantee. A scan holds the matter's source mutation
lock, captures its collection/set membership under the workspace lock, and
releases the workspace lock before matching. Other matters can continue using
workspace storage during the scan. Source changes in the searched matter wait
for the scan; membership edits during a scan affect the next request, where the
fingerprint detects a changed result population.

Synthetic file-backed regressions cover a result at its configured character
limit, overflow before an unread large tail, a slow read that expires before
decoding, serialized whitespace exhaustion, and oversized complete or unfinished
first records. Existing cross-unit Boolean proofs and proximity results retain
their semantics; invalid source tails still invalidate the entire scan.
Decoded unit numbers, text and displayed locator types are validated inside the
source-reading boundary. Corrupt locators produce the documented unavailable
response rather than a server error or an apparently exact partial total.
Pagination fingerprints include both media timestamp endpoints, even when line
locators and text remain unchanged; retiming a media projection invalidates the
previous result fingerprint and requires a fresh search.
Timed media projections must also have consecutive segment numbers, paired
timestamps, nondecreasing start times, strictly later endpoints and endpoints
within the producer's two-second duration allowance. These checks apply to
inline and file-backed projections; corrupt or mixed timed/untimed locators
make the scan unavailable before it can return misleading seek links. Equal
starts and overlapping segments remain valid. Wholly untimed legacy media
keeps its ordinary unit links, and PDF page numbering retains its separate
coverage rules.

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
inputs, empty-input guidance, original-text previews, skipped-page links,
late phrase matches after isolated words, button-free advanced submissions,
transcript timestamps, conservative partial-PDF coverage, satisfied-branch
explanations, and a preview-stage deadline regression. Browser checks cover
the first-use form, a successful search, no-result guidance, keyboard submission
with visible focus, and a 390-pixel viewport without horizontal overflow.
The shared grammar's truth tables remain required.

Real PostgreSQL indexed exact-search acceptance is pending; no PostgreSQL
exact adapter is claimed. The same authoritative scan is used when a PostgreSQL
answer backend is configured. Large-population latency, concurrent-user load,
and persisted-search restore acceptance require the future adapter and separate
evidence. No deployment or confidential-workload acceptance is implied.

Concurrent browser searches first check membership in a short synchronous
dependency, keeping storage work off the async event loop. Authorized requests
with validated search inputs then use non-queuing asynchronous admission before expensive scan dispatch:
one active request per authorized matter ID and at most four per app instance.
Extra authorized requests receive HTTP 429 with a short retry hint; inaccessible
matters return the same 404 whether idle or busy. This keeps waiting scans from
occupying every shared request worker; the scan/preview deadline and matter
source-version lock remain independent controls.

## September 9 cleanup on the accepted baseline

The Find sources and proximity components are rebuilt on the selected accepted
baseline without the deferred Reports integration. Typed controls, matter
membership, saved scope and query syntax are checked before scan admission.
Empty forms and invalid submissions keep their normal form/error responses
while another scan is busy; valid concurrent scans still receive a retryable
429 before scan worker dispatch. The authorization lookup remains a short
synchronous dependency, and slots use the authorized matter ID.

Transcript previews format the production transcript projection's millisecond
positions as recording timestamps and retain seek links and segment anchors.
A unit explaining several positive conditions shares its bounded excerpt
allowance across those conditions, including both ends of long proximity spans.
Ellipses mark omitted text. This remains a bounded reference scan, not an indexed
or persisted search receipt; all existing coverage exclusions and fingerprint
checks apply.
