# Matter workspace layout

Matter pages share a full-width outer shell and the same content gutter.
Review, Work product, Case notes, and the other matter tools keep their header
and navigation aligned when moving between pages. Reading cards may still use
an inner reading width. `static/workspace-layout.css` owns this shared geometry;
feature styles own the content inside it.

Long right-hand content must not make left-hand controls unreachable:

- The fixed global matter rail scrolls its list independently, keeping its
  creation, search, and collapse controls available.
- On desktop, Saved conversations stays within Review's scrolling pane. Its
  list scrolls independently and reserves the actual height of the sticky
  question composer, including when that composer grows. Tablet support drawers
  reserve the composer's bottom offset too, including after viewport resizing.
  On short tablets with support open, the entire history panel scrolls so its
  heading and filter cannot consume all available space above the composer.
- The conversation layout stacks at 760 pixels and below. Its non-sticky
  history retains the 250-pixel list cap and scrolls away above the active
  conversation. At 761–900 pixels, history remains beside the conversation
  both with and without a support drawer.
- Case note tools use the document scroll so note creation and discovery
  controls stay reachable without a nested sidebar scroll trap.
- Independent navigation and conversation scroll regions remain keyboard
  reachable. Case note tools intentionally use ordinary document scrolling.

Run the bounded synthetic browser acceptance with a matching Chrome and driver:

```console
python scripts/browser-accept-workspace-layout.py \
  --chrome-binary /path/to/chrome \
  --chromedriver /path/to/chromedriver \
  --output /tmp/recordbench-layout-acceptance
```

The script uses temporary invented matters, conversations and notes, an
unavailable generator, and an explicit synthetic storage policy. It clears
inherited RecordBench service settings. It checks alignment at 1800×1000,
1440×480 and 390×844, then uses native wheel events and keyboard navigation to
verify independent scrolling beside long content. Support-open checks cover
761, 820 and 900 pixel widths, then resize the open page to 820×650 without
navigation and hit-test the last saved-conversation link above the composer.
Without support, the same tablet widths verify separate history/content columns,
independent list scrolling and unobscured active content; the 760/761 boundary
checks the stacked list cap and confirms history scrolls out of the reading area. The output contains local
screenshots and a receipt identifying the tested commit and working-tree state.

This layout-only contribution starts from the accepted selected integration.
The frozen review-acceptance manifest remains unchanged: its integrity tests
pass without importing the broader integration's changed media test or updating
its recorded digest.

## Save an assistant passage during review

Each generated claim in the assistant dock has **Save passage to case notes**.
The existing save checks matter access and current citation support, creates a
suggested note for human review, and deduplicates repeated saves. A save only
updates the claim's accessible inline feedback; it keeps the reader document,
section, scroll, URL, filters, selected chat and unsent question in place. A
pending response cannot replace a newly opened reader or chat. An uncertain
response can be retried safely. Saving does not confirm the generated claim.

Without JavaScript, the form returns to the validated same-matter reader URL
with a notice or error. A full page submission cannot preserve an unsent
client-only draft or arbitrary pixel scroll; source section and filters remain
in the return URL. Full conversation's existing forms and redirects still work.
No new storage, conversation, graph or generation contract is introduced.

Supplemental browser acceptance uses an explicitly selected Chromium executable
and Playwright available to Node, plus the existing Python development environment:

```console
node scripts/browser-accept-assistant-passage.cjs /path/to/chromium /tmp/new-dock-acceptance
```

It starts an ephemeral loopback application with generated text and an unavailable
model. The receipt and screenshot contain only synthetic evidence. It checks
keyboard feedback, retained reader/composer state, repeated saves, pending chat
and reader navigation, Back/Forward, reload and JavaScript-disabled submission.
Simulated error responses test inline recovery; the Python route regressions in
`tests/test_assistant_passage_save.py` separately prove real stale-citation,
revoked-access and CSRF rejection without writes. This supplemental run does not
replace the pinned browser or other hosted Quality gates.

## Manual source review workspace

**Document review** opens the source library. **Automated screening** retains
criterion-based extracted-text review. The source reader offers a compact header,
optional filtered queue, previous/next source navigation, and an adjustable
questions/notes pane. Queue visibility and pane width are optional local browser
preferences. Source details and extraction limitations remain expandable; hiding
these details does not establish complete extraction.

**Ask using this source** selects the next question's source scope without
replacing the reader. Saved answers remain labeled as historical answers with
their own citations. Changing question scope does not change the evidence behind
an earlier answer. Asynchronous assistant operations are fenced against newer
conversation and scope choices. The full conversation and report/export routes
remain available.

**Write a note** saves human-authored prose with canonical source support into
existing Case notes, with manual origin and Needs review status. Saving a note
or marking a source reviewed does not confirm its claims, transcript or entities.
An immutable draft identity makes uncertain retries safe; **Write another note**
starts a separate note, including on the same passage. Before sending, the reader
keeps only retry identity and source coordinates in that browser history entry,
so Back and reload cannot silently turn a restored draft into a second note.
Note prose is not persisted by this mechanism. If the browser does not restore
the text, inspect saved Case notes or explicitly start another note. The server rechecks matter
access, source version and extraction basis before saving. A changed source is
rejected for renewed review. Existing AI passage saves retain suggested status
and preserve later human decisions on retries.

PDF notes identify the source page selected by RecordBench's section controls.
The embedded browser PDF toolbar does not report page changes to the outer
reader; select the matching RecordBench section before annotating another page.
Media notes capture a playback position and attach the canonical transcript span
containing it. A position without transcript support cannot produce a
source-linked note through this form. The playback element remains mounted when
questions, notes, queue visibility or pane width change. Source changes and
transcript pagination use normal navigation; they do not promise uninterrupted
playback across documents or transcript page boundaries.

Without JavaScript, the note form is available in normal document flow and
successful submissions return to a validated same-matter reader URL. Validation
errors retain the submitted draft. Full-page navigation cannot preserve arbitrary
pixel scroll, native PDF toolbar state or an unsent client-only question.

Supplemental deterministic acceptance:

```console
.venv/bin/python -m pytest -q tests/test_manual_review_notes.py tests/test_assistant_passage_save.py tests/test_answer_cited_context.py tests/test_review_acceptance_pack.py
node scripts/browser-accept-manual-review.cjs /path/to/chromium /tmp/new-manual-review-acceptance
```

The browser fixture generates a PDF and a short video, supplies deterministic
transcript/answer data, and delays request responses deliberately. It checks
source-linked human notes, uncertain retries, stale history/ask/poll/cancel
responses, explicit source scope, mounted playback, filtered navigation, keyboard
focus, layout preferences, narrow screens and the non-JavaScript note fallback.
A 640×302 CSS viewport approximates the available space at 200% zoom; this is
not native browser zoom qualification. Transcript pagination and playback-time
restoration through browser history remain unqualified. This synthetic cloud
verification does not establish real-model, GPU, security-profile, recovery or
production-server acceptance, and does not replace the current Quality gates.
