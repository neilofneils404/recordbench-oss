# Report compiler: human review capacity

This is an isolated compiler foundation extracted from the public #44 head
`e5fbd9ac3857c53453402589b30b82aee13c84ed` and reconciled against accepted main
`1fed77a2c50686b073e4c3255421d77aa16fefe5`. It includes the pure compiler and
synthetic tests, with the human-capacity correction below. It does not enable
a Reports composer, background jobs, or a new persistence format. Those parts
of #44 remain separate work; the existing Report workflows are unchanged.

## User outcome

A generated finding or a note classified under several entity categories must
not crowd a retained human note or disagreement out of the draft. The compiler
reserves one content section for each retained, nonempty human record before
allocating generated sections or saved machine findings. Original human text,
source citations, author, revision, and review status remain attributed.

When separate People, Places, and Things copies would consume another human
record's reserved slot, the compiler places the note once with all its category
labels. If retained human records alone exceed the section budget, compilation
fails with a request to reduce the selection or increase the budget. It does
not return a partial human record set as a completed draft.

## Boundaries

- The material budget still controls which input materials are admitted.
  Materials beyond it remain listed in `omitted_material_ids`.
- A complete relevance check may exclude unrelated review records. Unavailable,
  rejected, or incomplete checks preserve human records with an explicit
  unconfirmed-relevance note, even when source generation succeeds. Empty records
  do not reserve slots. `retained_unclassified_review_material_ids` identifies
  the unchecked records actually retained in the draft.
- Relevance batches contain at most eight records, matching the shared answer
  schema and verifier claim capacity. Smaller batches still share the configured
  model-call budget; unchecked later records remain available as unconfirmed
  review. A response with omitted, invalid, or repeated classification claims
  cannot prove the other records irrelevant. Generation verification retains a
  separate duplicate-claim count so normalization cannot hide consumed output
  slots; it does not label duplicate claims as unsupported statements. A classifier
  limitation also leaves the batch incomplete: an ambiguous relevance assessment
  cannot exclude an unreturned human note.
- A note longer than the model's per-item input limit is never marked completely
  classified from its prefix. Its full original text remains available, and
  `truncated_review_material_ids` identifies the affected records alongside the
  existing truncated-character count.
- Generated candidates are bounded to `max_sections` while model calls finish.
  Content allocation stays within that limit; the coverage ledger adds one
  separate section. Generated or machine sections can still be omitted and are
  disclosed by the coverage ledger.
- Category coalescing retains the original text and every classification label;
  it is not counted as omitted human material. `omitted_human_material_ids`
  continues to describe topic relevance exclusions.
- Citations must fit the existing 6,000-character Report excerpt limit before
  model work starts. Oversized passages fail explicitly; the compiler does not
  shorten original citation text to make a preview savable. The compiler and
  persistence validation share the same limit.
- Selected records must also fit the unchanged 100-citation per-section Report
  limit before model work, including human notes, saved gaps, and machine
  fallbacks. The compiler and persistence validator share this limit. Excess
  citations fail explicitly; exactly 100 passages remain intact through saving
  and export. Generated section admission enforces the same bound.
- Empty or whitespace-only citation excerpts also fail admission, including
  mixed valid/blank selections. They cannot make a machine assertion appear
  sourced or hide an unsupported human-note warning.
- Source batches fit the same eight-claim answer capacity. Unvisited passages,
  unrepresented passages in full outputs, and truncated or rejected outputs
  remain incompletely analyzed; their original saved findings stay available
  through the attributed fallback. Duplicate-normalized output cannot establish
  complete source coverage either.
- Repeated generated claims with the same text and evidence set occupy one
  section per category regardless of evidence order. The first claim's citation
  order is preserved for display; distinct evidence sets remain separate. The
  verifier counts these duplicates by text and an order-independent evidence set
  before source-completeness decisions, including non-saturated outputs.
- Verified limitations and evidence notices stay in each generated finding's
  readable body, before its review basis. Source-supported limitations include
  their citations and identify the corresponding section-local source numbers.
  Service-authored omission notices remain labeled qualifications without
  invented citations. Transcript notices retain their playback and reliability
  cautions in saved Reports and exports. These qualifications share the finding's
  section and text budgets, so capacity cannot drop them independently.
- Verifier omission notices have separate, uncited metadata and a separate
  `Verification notice` paragraph. A source-supported limitation never attributes
  verifier behavior to its source. Legacy conversation answer fields and display
  remain compatible; this compiler uses the explicitly separated metadata.
- Timeline headings and sort keys consider the source-supported limitation as
  well as the claim. Common date hedges such as may, might, approximate, estimated,
  circa, uncertain, and unconfirmed retain the date wording without claiming an
  exact date, including saved records with a supplied date label. A limitation
  cannot introduce an event date missing from the claim. Transcript and media-clip
  citations keep generated and saved timeline dates non-exact regardless of the
  phrasing or a supplied date label. This decision follows the finding's own
  support: document-only findings in a mixed source answer can retain exact dates.
- Compiler version 9 changes the fingerprint so earlier previews cannot share
  an identity with the corrected allocation, relevance, citation, and
  qualification policy.
- This work does not resolve #44's separate finding about distinct machine
  assertions sharing a passage, or its deleted-result and cancellation UI
  findings. This foundation is not acceptance of the full #44 workflow.

## Synthetic validation

Run `python -m pytest -q tests/test_report_compilation*.py` in the contributor
environment. Capacity regressions exercise generated and offline machine work
before a disputed note, multiple entity categories, insufficient human capacity,
empty and topic-excluded notes, and initially available model failure. Mixed
classification/source outcomes, partial entity classification, exact citation
persistence limits, reversed-evidence duplicates, classifier output capacity,
matches beyond a truncated note prefix, and persisted/exported limitations and
transcript notices have focused regressions. Additional real-service regressions
cover qualified timeline ordering, ambiguous relevance limitations, and reversed
evidence order in duplicate output; exact-date and distinct-claim controls remain.
Transcript-date regressions exercise real verification and mixed source packets;
citation-count boundaries verify full persistence and Markdown export.
Existing compiler tests also exercise grounding, coverage, cancellation, export text
limits, current Report storage compatibility, and source snapshot fingerprints.

No schema, storage, authentication, dependency, model revision, or deployment
behavior changes are included. Deterministic synthetic generators test the
allocation contract; they do not establish model quality or live-workload
readiness. Full application and transcription suites, Compose validation,
Python compilation, publication checks, and final-commit hosted review remain
the contributor and acceptance gates.
