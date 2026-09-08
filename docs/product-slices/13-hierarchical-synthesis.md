# 13: Synthesize a substantial review without losing source support

Status: proposed. Depends on 11 or 12 and their persistent findings.

## Finding and outcome

The current final research answer uses a newly selected packet of at most 12
passages. It does not consume the saved pass findings as a structured body of
work. More searches alone can therefore leave the final answer shallow.

## Small implementation

Produce issue-level or source-group summaries from persisted findings, then a
matter-level synthesis from those summaries. Every intermediate claim must keep
its original source/version/location support. An intermediate summary is not
itself an evidence source. Fetch the necessary originals to verify final claims.

First support one issue-oriented synthesis with supporting evidence, competing
evidence, and unresolved questions. Keep page/token budgets, checkpoint state,
omitted groups, and stop reasons explicit. Use section-sized generation calls
instead of treating the current short-answer output cap as a whole-report budget.

## Code and acceptance

Start with `_process_research_job`, `generation.py`, workflow checkpoints, claim
verification, and `work_product_exports.py`. Store enough provenance to
revalidate intermediate and final claims after a source changes.

Synthetic acceptance distributes decisive support and contradiction across more
than 12 units. Verify the final synthesis retains both with original citations,
does not promote unsupported intermediate text, survives restart, and flags
partial processing. Run representative local-model evaluation for evidence
recall and false claims in addition to deterministic plumbing tests.

Version new persisted records and show backup/clean-restore compatibility.
No model swap is assumed; any swap requires the repository's model evidence.
