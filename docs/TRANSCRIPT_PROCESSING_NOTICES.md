# Transcript processing notices

A recording can have a usable transcript even when automatic speaker attribution
fails. The review page shows the saved processing outcome above the player and
transcript, including after a reload. Failed speaker attribution is explicitly
identified; unreviewed fallback speaker labels are placeholders, not evidence
that the recording contains only one speaker. Skipped speaker attribution is
shown separately. Successful attribution is still an anonymous model grouping,
not identification of a person.

Review the recording before assigning names or relying on transcript wording.
Human corrections retain their normal attribution and do not erase the original
processing outcome. The optional generated overview has its own status.

Word, Markdown, Text and JSON exports preserve the staff-facing processing
notices. JSON includes an additive `processing_notices` array when applicable;
the complete-matter bundle preserves it in transcript JSON and Markdown files.
SRT, VTT and CSV remain transcript rows only. Include the JSON export when sharing
those formats so the processing limitation travels with them. Notices are never
inserted into timed speech cues. Backend diagnostics are not included.

The synthetic workflow regressions cover failed, skipped and successful speaker
attribution, an imported failure warning without a quality-status field, escaped
warning text, individual exports and complete-matter bundles:

```sh
python -m pytest tests/test_matter_media_workflow.py -k processing_notices -q
```
