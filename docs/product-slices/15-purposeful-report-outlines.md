# 15: Make Reports answer a concrete review question

Status: proposed. Depends on 14; integrates 13 when available.

## Finding and outcome

The current report builder starts with title/purpose and manually assembled
sections. Purpose is stored metadata, not a workflow that assembles a useful
analysis. A report's formatting cannot compensate for shallow source review.

## Small implementation

Offer two initial deliverables: an issue review and a chronology. For an issue
review, prefill an editable outline for question, supported findings, competing
accounts, missing evidence, and next review actions. For a chronology, use dated
entries with source support and explicit uncertainty about ambiguous dates.

Populate only from reviewer-selected saved findings or a named review run.
Show a material-selection preview before inserting sections. If evidence is
missing, keep a clear empty/needs-review section rather than inventing prose.
Later use synthesis from 13 within this same outline and provenance contract.

## Code and acceptance

Start with Reports routes/templates, `add_*_to_report`, notebook/finding source
selection, section persistence, and Word/Markdown rendering. Explain whether a
section is manually written, copied from a run, or generated from selected
support. Preserve authors' edits and existing stale-edit recovery.

Synthetic/browser acceptance builds both deliverables, verifies each factual
section's original support, edits/reorders it, and exports it. Include conflicting
dates, an unresolved question, an empty evidence selection, and stale citations.
Do not attach citations merely because they appear somewhere in the source run.
This first slice requires no new model or automatic legal conclusion generator.
