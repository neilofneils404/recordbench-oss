# Search and document review navigation

Matter navigation exposes **Search** for exact matching in extracted document
contents. **Sources** labels its separate filename/folder filter explicitly and
links to content search with the current collection and saved source set. Search
retains its existing Boolean, phrase, proximity, eligibility, exclusion and
population-change behavior; a missing match does not establish absence from
unextracted material.

A search hit opens its existing document or recording inspection page at the
matching section. Return to review context restores the complete search URL,
including filters, page and the computed population fingerprint, even on the first
results page. A changed population requires an explicit search refresh. Ask using this source uses
the existing single-source scope and retains that return link through question
submission, status polling, completed answers and investigation startup/completion.
Investigation cancellation, resume/retry, run selection, cited support and returns
to the conversation carry the same validated origin, including error redirects.
Return paths
are validated against the current matter; authorization is still checked at the
destination. The link restores the search request, not a cached result snapshot.
Changed populations continue to require the existing search refresh.

**Case conversation** names the question/investigation workspace. **Document
review** opens saved criteria and source screening. Sources offers Review all
extracted text before its long source table. In Document review, launch controls
stay ahead of the decision ledger even when a saved run is selected. Progress,
safe cancellation/resume and a coverage notice link to the complete text ledger.
The text-ledger page also places saved-run controls before extraction/source
lists. Cancel and Resume are shown only to the run owner; administrator read
overrides do not expose controls they cannot use. Legacy and resource-limited runs
retain their existing resume restrictions.
A completed run can still have failed ranges, missing extraction or unavailable
sources; the coverage ledger remains authoritative.

This change is independent of the collection-intake work in PR #89. Integration
points for adjacent work are the shared matter tabs, the existing source return
query parameter, and the review-controls/coverage sections. It adds no viewer,
discovery execution, extraction policy, model, schema or deployment behavior.

Validation uses synthetic route regressions, the application suite, and pinned
exact-search/full-text-review browser journeys. Browser assertions cover the
visible Search entry, paginated search return after source inspection and scoped
questions, and launch/coverage placement before the decision list at desktop and
390px widths. Existing tests retain cross-matter access, complete-search and
full-text coverage/resume checks.

The frozen Review acceptance pack updates the conversation-composer node digest,
the two affected test-file digests and the resulting content fingerprint.
Only navigation label assertions changed, to Case conversation and Document
review. The question,
workflow behavior, fixtures, case membership and acceptance criteria are retained.

Search returns also survive completed-answer citations, investigation details,
and source review-state changes. Read-only administrators see inspection links
without unavailable question actions. Matter tabs scroll whenever their content
exceeds the available pane, including intermediate desktop widths.
