# Alpha usability work

The user journey should connect collection intake, processing, content search,
document inspection, and cited candidate findings without requiring users to
learn internal workflow terminology.

The first change requires a collection name in the browser, presents file and
folder selection equally, and adds cancellation to selection review. See
[receipt behavior and validation](INTAKE_RECEIPTS.md#deliberate-browser-selection).

## Follow-up priorities

| Order | Problem | Intended outcome |
| --- | --- | --- |
| Next | Content search is hidden behind Review and Find sources | Visible matter Search entry, clear distinction from filename filtering, and access from hits to source inspection and scoped questions. Build on existing exact search. |
| Next | Full-text review actions and progress are separated by long source lists | Present the extracted-text action before the list and keep progress close to it, with clear coverage and failure states. |
| Next | Dusk has pale text on white controls | Audit source status cards, filters, bulk actions, focus states, and disabled controls with computed contrast and browser screenshots. |
| Following | Review conflates conversation and document inspection | Use distinct, consistent labels and preserve context between chat, search, and source review. |
| Following | Document inspection requires repeated navigation | Persistent source list beside the viewer, previous/next controls, keyboard navigation, and retained filters across documents and recordings. |
| Following | Folder organization is hard to discover | Improve visibility of existing collection and folder browsing; validate nested synthetic collections and bounded paging at scale. |
| Following | Entity and date discovery requires disconnected actions | Connect intake and full-text coverage to existing entity/chronology workflows with clear progress, cited suggestions, retry, and human acceptance. |

Automatic discovery after ingestion needs a separate product and capacity decision.
Existing deterministic extraction and model-backed analysis have different coverage
and cost; neither should imply complete or verified findings. Any model changes
require the repository's pinned-model and representative evaluation evidence.

Use a synthetic end-to-end scenario for subsequent work: upload a named folder,
find a term in its contents, inspect consecutive matching records, and review a
suggested person and date without losing collection context. The table describes
planned work, not features delivered by the first intake change.
