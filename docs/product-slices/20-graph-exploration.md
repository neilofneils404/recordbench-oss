# Slice 20: source-backed graph exploration

Status: implemented locally; upstream acceptance pending. The
[feature contract](../GRAPH_EXPLORATION.md) records behavior and local evidence.

## Reviewer outcome

From a saved entity, open an evidence graph, inspect the events/assertions that
explicitly include it, follow another saved identity, and inspect supporting and
competing original passages. Documents and recording transcripts use the existing
source locators. The same relationships remain readable in an accessible list.

## Scope

- A read-only, bounded projection of the existing entity and assertion records.
- One entity neighborhood per request, with explicit record pagination and counts.
  Following another current entity loads its own neighborhood.
- Use entity -> assertion -> entity role edges; never create a direct factual
  relationship from co-appearance, matching names or semantic similarity.
- Preserve separate same-name IDs, human review status, raw dates, date uncertainty,
  supporting/competing attribution and original source/version/locator references.
- Current original-support validation and authorization use the existing source
  guard and shared unit of work. Changed/missing identity roles remain visibly
  historical and must not be silently mapped to another identity or traversed.
- Historical support remains inspectable as retained text; current-source actions
  are available only after existing exact-reference validation.
- No schema, source bytes, model portfolio, queue, deployment or stored graph change.
- Keyboard-accessible navigation, readable small-screen fallback, escaped labels,
  scoped styling, useful empty states, and no external browser assets.

## Required acceptance

Synthetic cases must include a same-name unrelated person, two explicit linked
identities, a competing original, an uncertain date, a changed role, an unavailable
original, pagination, and matter-access denial. Verify entry from entity detail,
following a current neighbor, inspecting an assertion and original, return context,
and useful behavior with the generator unavailable. Limits must state exactly
which records and support rows are displayed; no graph-wide completeness claim.

Native visual embeddings, automatic relationship inference, collection-wide graph
construction, query-time agent traversal and million-record qualification follow
separate contracts and are not accepted by this slice.
