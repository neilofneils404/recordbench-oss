# UI usability cleanup plan

Status: local implementation and browser validation completed for the core
repair packets; release and manual device checks remain. See the
[implementation record](UI_USABILITY_CLEANUP_IMPLEMENTATION.md) for exact
coverage, evidence, and outstanding gates. The packet specifications below
remain the intended acceptance targets, not a claim that every matrix cell ran.

Baseline: `a49133f1fe022fb098f2519aea007fa562570371`.
Read the [companion audit](UI_USABILITY_AUDIT.md) for screenshots and limitations.
The maintainer subsequently authorized implementing and improving the proposed
experience. The resulting changes are local and reviewable; nothing has been
published or deployed.

## Outcome and scope

Design for modern 27-inch desktops at larger operating-system scaling/fonts,
spacious 4K desktops at small scaling, and mobile. Respond to available content
space, not assumptions about monitor age or diagonal size. Preserve the visual
identity and workflow contracts while keeping tasks reachable and text readable.

The audit confirmed a 1024-by-768 Case notes state with both side panels open in
which the note library shrank to approximately 147 CSS pixels for 210 pixels of
content. The statistics strip had approximately 443 pixels available for 554
pixels of content. It also confirmed mobile navigation with 336 pixels available
for 832 pixels of links; the selected Sources link was outside the visible strip.
At 3840-by-2160, note prose stretched approximately 2781 pixels at 15-pixel type.
At widths of 760 pixels and below, the shared header hid Activity, Appearance,
account, and sign-out controls. Measurements describe specific audited states.

The reported Case notes scroll failure was **not** reproduced in tested states.
At 1440-by-480, End reached the suggestion button. At 1024-by-768 with both panels
open, submitting suggestions succeeded. Preserve scrolling while checking enlarged content.
Mobile Sources scrolls within its container; status/action discoverability is
the concern, not established page-wide overflow.

Preserve authentication, storage, schema, models, source support, extraction,
review decisions, and export meaning. No framework/design-system migration,
broad renaming, or stylesheet reorganization. The older
[usability priorities](USABILITY_IMPROVEMENTS.md) are historical input, not a
completed checklist or authorization for unrelated features.

## Execution and ownership

Use one packet per reviewable change. Read `AGENTS.md`, `CONTRIBUTING.md`, and
`docs/PUBLIC_ALPHA.md`. Verify the baseline, preserve unrelated work, and retain
publication/final-commit review requirements when publication is authorized.

Suggested order: **U0 → U1 → U2 → U8a → U3 → U4 → U5 → U6 → U7 → U8b**. Documentation
and fixture investigation can overlap, but only one worker owns
`src/case_intelligence/static/case-intelligence.css` or
`src/case_intelligence/static/case-intelligence.js` at a time. Rebase dependent
packets before validating; an old screenshot is not evidence for a changed head.

Use low reasoning for mechanical changes with fixed acceptance criteria; medium
for geometry, asynchronous state, focus, or integration. Give workers only their
packet, constraints, relevant files, and evidence. Escalate specific unresolved
reproductions rather than repeating the entire audit.

## U0 — Reusable fixture and evidence scaffold

**Dependency:** none. **Reasoning:** medium initially; low for receipt plumbing.
**Owner:** `scripts/browser-accept-workspace-layout.py`,
`scripts/synthetic_browser_environment.py`, `scripts/run-browser-acceptance.py`,
`tests/test_browser_acceptance_runner.py`, and narrowly necessary fixture helpers.

Reuse the disposable layout seed: long notes/conversations, many matters, and
an original-source support token. Add a bounded
synthetic person/place/date source, long labels, and explicit panel states. Use
`UnavailableGenerator`, disabled learned retrieval, temporary storage, test
authentication, and the existing environment isolation. Bind only loopback.
Never discover or reuse an installed node's credentials or runtime.

Separate baseline observations from assertions intended to become gates. Record
the known defects without adding deliberately failing tests to required CI.
Each later packet adds its passing regression when its fix is ready. Align the
layout receipt with the runner's required `passed`, `synthetic_only`, and `checks`
fields; its existing receipt is not directly compatible. Keep bounded artifacts,
timeouts, process cleanup, and fresh-output-directory protection.

**Acceptance:** startup needs no model/deployment; receipt failures cannot report
success; capture browser, viewport, panels, commit, and dirty-tree state. Existing
journeys remain unchanged. Run runner/isolation tests. Promote new layout checks
to CI only after the repaired journey passes in U8.

## U1 — Case notes at constrained widths and heights

**Dependency:** U0. **Reasoning:** medium.
**Owner:** notebook selectors in `case-intelligence.css`, scoped geometry in
`static/workspace-layout.css` where appropriate,
`templates/workbench_notebook.html`, and the layout journey.

Make the notebook layout respond to the actual width available after the matter
rail and assistant consume space. Stack tools and saved notes before either
column becomes unusable; make the statistics strip reflow within that same
available width. Prefer container-sensitive layout or an equally bounded
existing-shell solution over additional arbitrary device breakpoints.

Retain independent tool scrolling only where a useful height remains. In a
stacked or enlarged-content state, ordinary document flow must keep the complete
form and suggestion action reachable. Do not hide overflow to conceal content or
require users to close panels to recover the form.

**Acceptance:** at 1024-by-768 with both panels open, no notebook child forces
horizontal page overflow and labels, fields, results, and actions remain usable.
At 1440-by-480, wheel and keyboard reach the suggestion action; submit it, verify
synthetic candidates, and open their source support. Cover 390 and 320 CSS-pixel
widths, long notes, an error message, and 200% browser zoom. Preserve the existing
working collapsed-assistant path. Run notebook/conflict tests and the layout
journey; assertions must test reachability and activation, not CSS strings alone.

## U2 — Reachable navigation and global actions

**Dependency:** U0, U1's shared stylesheet ownership released.
**Reasoning:** medium.
**Owner:** `templates/workbench_matter_tabs.html`, `templates/workbench_base.html`,
their scoped CSS, minimal navigation JS, and shared-navigation browser assertions.

**U2a, global controls first:** replace the mobile `.user-zone { display:none }`
behavior with a compact, visible global-actions disclosure. Keep Activity,
Appearance, account information, and sign-out available without changing their
actions or security behavior. Verify all four below/at/above 760 pixels, at 390
and 320 pixels, and with enlarged text. Sign-out must be discoverable; exercise
its actual behavior only with a disposable authenticated fixture.

**U2b, separate follow-up change:** keep existing links at generous widths. Expose the
current section and a clearly labeled section disclosure containing the same
destinations. Prefer a native disclosure with normal links over a custom ARIA
menu. Preserve route parameters, fragments, selected-section mapping, and the
processing-status include. Choose the transition from available content width,
including open side panels.

**Section acceptance:** all nine existing destinations are discoverable and operable at
390 and 320 CSS pixels; the current destination is visible before interaction.
Keyboard users can open the disclosure, reach its last link, and navigate.
Closed content creates no hidden tab stops. Long labels wrap without clipping.
Desktop link navigation and the existing `aria-current` values remain correct.
Validate live resizing in both directions and one narrow desktop state. Avoid
replacing this problem with an undiscoverable horizontal strip.

## U3 — Labels and selected-state consistency

**Dependency:** U2. **Reasoning:** low once the audited control list is fixed.
**Owner:** `templates/workbench_work_product_tabs.html` and only the specific
form templates identified by the audit; focused rendered-template tests.

Add `aria-current="page"` to the selected Work product subsection; main matter
navigation already supplies it. Label the four audited Sources bulk controls:
`action`, `collection_id`, `source_set_id`, and `source_set_name`. Use persistent,
associated labels. Preserve field names, script-referenced IDs, submission
parameters, and validation behavior.

**Acceptance:** exactly one appropriate current link per navigation group;
every changed control has an accessible name that survives entered values and
validation errors. Visible labels stay readable at narrow widths. No duplicate
IDs or new tab stops. Use rendered HTML tests for associations and a short
keyboard/browser check; do not add snapshots of entire templates.

## U4 — Skip navigation and visible keyboard focus

**Dependency:** U2–U3. **Reasoning:** medium for shared-shell integration.
**Owner:** `templates/workbench_base.html`, necessary main-content targets,
shared focus CSS, and layout keyboard checks. Coordinate JS edits with U5.

Add a first-focusable skip link targeting the current page's actual main content.
Use one unique target; do not wrap an existing main element in a second main
landmark. Give interactive controls an opaque, visible outline in both themes,
including note actions, navigation, and disclosures. Provide a forced-colors
fallback instead of depending on box shadows. Respect sticky headers.

**Acceptance:** Tab from page entry reveals the skip link, activating it moves
focus into the correct content, and the next Tab continues there. A focused
control is not entirely covered by a fixed header, composer, or drawer. Check
links, inputs, selects, buttons, and summaries in Light and Dusk, plus a
forced-colors browser check. Use computed contrast and interaction; retain native focus
behavior where it already works. Screen-reader spot checks are manual evidence,
not a claim of comprehensive accessibility certification.

## U5 — Activity drawer focus and refresh lifecycle

**Dependency:** U4. **Reasoning:** medium.
**Owner:** activity controller in `case-intelligence.js`,
`templates/workbench_base.html`, `templates/workbench_activity_center.html`,
activity selectors, and a focused browser regression.

Treat the scrim-backed drawer consistently as a modal interaction. Provide
dialog semantics and a reliable close control during initial loading. Move focus
inside once opened, contain keyboard traversal, and make covered content inert
while retaining its previous state for restoration. Polling currently replaces
drawer content; preserve its scroll position and focus on the surviving action, or a predictable
safe target if that action disappears. Do not steal focus on background refresh
while the drawer is closed.

**Acceptance:** the audited first-open failure is fixed: Tab cannot move from
the trigger into underlying Appearance controls. Test slow first response,
failed response, repeated open/close, refresh while a link is focused, and close
during an outstanding request. Escape, close button, and scrim restore focus to
the opener. Resize an open drawer at mobile width. Preserve activity data,
polling cadence, privacy filtering, and existing Escape behavior.

## U6 — Scoped Dusk text-ledger contrast

**Dependency:** U0 and shared CSS availability. **Reasoning:** low after reproduction.
**Owner:** `.text-review-page .text-review-ledger` CSS,
`templates/workbench_text_review.html` only if necessary, and contrast coverage.

The text ledger has hard-coded pale header/border colors. Capture the actual
rendered Dusk state and measure foreground/background combinations before
changing it. If confirmed, replace only those incompatible surfaces and ink
values with suitable existing theme variables. Reuse the computed-contrast
helper from `scripts/browser-accept-dusk.py`.

**Acceptance:** ordinary ledger text meets 4.5:1 contrast, large text 3:1, and
meaningful focus/control boundaries 3:1 in affected states. Light remains
readable. Keep source/location, outcome, and limitation columns intact. The older
Sources Dusk issue already has scoped CSS and browser checks; change Sources
colors only if a fresh reproduction shows a remaining failure. An unreproduced
candidate is recorded as such, not fixed speculatively.

## U7 — Mobile Sources with visible status and actions

**Dependency:** U2–U4; shared CSS/JS ownership available.
**Reasoning:** medium.
**Owner:** `templates/workbench_setup.html`, source-library selectors, and source
browser regressions. Compact source previews are outside scope unless sharing
the changed selector causes a verified regression.

Present source rows as readable cards at narrow available widths. Keep source
name, preparation/review status, selection, and primary actions visible together.
Preserve the same bounded server-rendered page, filters, sorting, pagination,
selection values, and permissions. Avoid rendering duplicate interactive copies
for desktop and mobile. Adjust semantics deliberately when changing table-like
presentation; do not leave misleading row/cell roles on unrelated cards.

**Acceptance:** at 390 and 320 CSS pixels, users can identify a source, understand
its status, open it, and select it for an existing bulk action without sideways
discovery. Long filenames wrap; error and processing states remain explicit.
Desktop tables retain column alignment. Run source-library and folder-navigation
tests plus browser checks for filtering, paging, selection, and source return
context. Keep bounded horizontal scrolling for genuinely two-dimensional data
elsewhere; this packet does not redesign every table.

## U8 — Modern desktop proportions and final integration

**Dependency:** U8a follows U1–U2; U8b follows all packets.
**Reasoning:** medium for layout/integration, low for fixed typography changes.
**Owner:** audited typography/width/spacing selectors, completed browser
journey, runner allowlist/registration, and final evidence documentation.

**U8a, desktop proportions:** correct 4K Case notes early in the sequence. Start
prose around 65–85ch, a
product target rather than a WCAG mandate, and keep actions/support close to it.
Use extra width for useful task columns. Preserve reading order; no masonry or
global narrow-page cap. Keep desktop workflows efficient. Increase essential
small copy selectively with adequate line height; no blanket enlargement or
new global density preference. Prefer
44-pixel touch targets where practical and document applicable 24-pixel
minimum/spacing exceptions.

**U8a acceptance:** balanced layouts at 1440, 1920, 2560, and 3840 CSS-pixel widths,
including both panels open. Prose and action rows do not stretch endlessly.
No new truncation, overlapping controls, obscured focus, or lost
content under text enlargement or text-spacing overrides.

**U8b, final integration:** complete the matrix below, then register the repaired
layout smoke journey in the pinned runner.
Keep receipts and screenshots within existing artifact limits. Run the complete
required checks once on the integrated candidate; rerun affected checks after
any subsequent correction. Record unresolved failures rather than weakening
assertions or presenting a focused pass as full acceptance.

## Validation matrix and commands

Use pairwise coverage rather than every route × every state × every theme.

| Coverage | Minimum cases |
| --- | --- |
| Modern desktop proportions | 1440×900, 1920×1080, 2560×1440, 3840×2160; both panels open/closed pairwise |
| Constrained shell/navigation | 1024×768, 390×844, 320×568 |
| Notes and independently scrolling panels | 1440×480; 1024×768 with both panels open; 820×650 with support open |
| Changed breakpoints | One pixel below, at, and above each changed threshold |
| Enlargement | Actual browser zoom 125/150/200%; 400% reflow; larger fonts/text spacing; native OS scaling spot check |
| Keyboard | Entry, skip, last action, reverse traversal, Escape, focus after refresh |
| Themes | Affected text/control states in Light and Dusk; forced-colors focus; broad smoke in one theme |
| Phone verification | Portrait, landscape, touch scrolling, on-screen keyboard; one Safari/WebKit pass |

Record physical resolution, OS scaling, CSS viewport, device pixel ratio, and
browser zoom separately when available. A 4K physical display need not expose a
3840-pixel CSS viewport. Narrow emulation approximates reduced layout space;
device pixel ratio is not zoom, and CSS `zoom` does not prove native scaling. Existing
Chrome emulation with `mobile=False` establishes narrow-layout evidence only.
Document any unavailable real-device or assistive-technology checks as unrun.

Run from the repository root with the existing contributor environment:

```console
.venv/bin/python -m pytest -q tests/test_browser_acceptance_runner.py tests/test_synthetic_browser_environment.py
.venv/bin/python -m pytest -q tests/test_matter_notebook.py tests/test_notebook_conflicts.py tests/test_guided_usability.py tests/test_review_usability_repairs.py
.venv/bin/python -m pytest -q tests/test_source_library.py tests/test_source_folder_navigation.py tests/test_continuous_source_browsing.py
.venv/bin/python scripts/browser-accept-workspace-layout.py --chrome-binary "$CHROME_BINARY" --chromedriver "$CHROMEDRIVER" --output "$LAYOUT_OUTPUT"
.venv/bin/python scripts/run-browser-acceptance.py --output "$BROWSER_OUTPUT"
make check
```

Use fresh temporary output directories outside tracked source and verified
matching browser/driver paths. `--archives` supports verified offline archives.
Select focused tests per packet; retain integration/pre-commit gates. Worker
fixtures must wait for durable readiness, not sleeps or an eventual green rerun.

Receipts identify packet, head, dirty state, synthetic provenance, browser,
viewport, zoom, theme, panels, reproduction, result, screenshots, commands, and
unrun checks. Exclude runtime databases, credentials, deployment details, and
real material; inspect content/metadata before public upload.

## Compact worker prompt

> Implement authorized packet U[number] from `docs/UI_USABILITY_CLEANUP_PLAN.md`.
> Read its audit and repository rules. Verify head and prerequisites. Own only
> named files/selectors; coordinate CSS/JS ownership. Reproduce with the disposable
> synthetic fixture, correct narrowly, and add behavioral regression coverage.
> Preserve routes, source support, permissions, data meaning, and unrelated work.
> Run packet checks. Return files, user outcome, commands/results, evidence,
> concerns, and unrun gates. Do not expand scope, commit, publish, or open a PR
> without applicable authorization.
