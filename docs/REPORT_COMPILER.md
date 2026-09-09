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
- Repeated generated claims with the same text and evidence set occupy one
  section per category regardless of evidence order. The first claim's citation
  order is preserved for display; distinct evidence sets remain separate.
- Compiler version 5 changes the fingerprint so earlier previews cannot share
  an identity with the corrected allocation, relevance, and citation policy.
- This work does not resolve #44's separate finding about distinct machine
  assertions sharing a passage, or its deleted-result and cancellation UI
  findings. This foundation is not acceptance of the full #44 workflow.

## Synthetic validation

Run `python -m pytest -q tests/test_report_compilation.py tests/test_report_compilation_dedup.py` in the contributor
environment. Capacity regressions exercise generated and offline machine work
before a disputed note, multiple entity categories, insufficient human capacity,
empty and topic-excluded notes, and initially available model failure. Mixed
classification/source outcomes, partial entity classification, exact citation
persistence limits, and reversed-evidence duplicates have focused regressions. Existing
compiler tests also exercise grounding, coverage, cancellation, export text
limits, current Report storage compatibility, and source snapshot fingerprints.

No schema, storage, authentication, dependency, model revision, or deployment
behavior changes are included. Deterministic synthetic generators test the
allocation contract; they do not establish model quality or live-workload
readiness. Full application and transcription suites, Compose validation,
Python compilation, publication checks, and final-commit hosted review remain
the contributor and acceptance gates.
