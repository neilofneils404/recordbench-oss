# Independent review correction plan

Status snapshot, September 23, 2026: seven portable correction packets have
standalone CI receipts and remain **draft, open and unmerged**. The heads below
record the initial integration audit; follow-up corrections require fresh receipts.
Integration review and final-candidate validation are in progress. Dedicated
security-review completion (or a verified documented quota exception) and genuine
full-head maintainer acceptance remain pending. Track the bounded packets and
remaining product acceptance in
[issue #109](https://github.com/neilofneils404/recordbench-oss/issues/109); this plan
does not close that issue or claim installed/GPU/release acceptance.

Authoritative planning baseline: GitHub OSS `main` at
`a33d93b5302fc0f726f361ae2e3341883a4bdd77`, verified with `git ls-remote` and
an isolated fresh checkout. This is exactly the external review's commit.
The seven standalone packets started from that same revision, which remains the
verified protected-main baseline for this integration snapshot. Refresh GitHub and
record the actual base and candidate before each update or merge, preserving
unrelated work. The receipts below do not validate later corrections, base updates,
or the future combined candidate.

## Objective and evidence boundary

Correct misleading answer confidence, incomplete extraction presented as complete,
unsafe authentication fallback, and source-text failures without weakening
source provenance, privacy, authorization, or recovery. Review retention against
the intended workflow before changing deletion policy.

The external report describes synthetic reproductions in an isolated arm64 Linux
VM/container environment, with an injected generator and a clean-result malware
scanner stand-in. It is useful defect evidence, but is not a supported x86-64
installation, real-model evaluation, scanner acceptance, or GPU acceptance.
The source checkout was current GitHub OSS code; the limitation is the runtime
test environment, not the freshness of that source. Its reproduction package and
logs were not inspected in the initial planning pass. The packets use independently
written synthetic regressions. External-report test totals remain attributed
reports; the separately inspected GitHub Quality receipts below are evidence for
their recorded standalone heads only.

A GPU is unnecessary to demonstrate a deterministic verifier accepting supplied
text, a PDF OCR-selection error, a save-handler exception, or an authentication
configuration error. Fix these with reproducible application tests, then validate
the integrated product using the supported installation and model profiles.

Read [architecture](ARCHITECTURE.md), [security](SECURITY_MODEL.md),
[installation](INSTALL.md), [backup and recovery](STORAGE_AND_BACKUP.md), and
[release readiness](RELEASE_READINESS.md). Existing release requirements remain
in force. Keep all fixtures synthetic and all public evidence environment-neutral.
Do not copy operator paths, deployment configuration, identities, logs, or secrets
into this plan, fixtures, or handoffs.

## Triage ledger

The code observations below were checked at the planning baseline. None substitutes
for a current-candidate end-to-end reproduction.

| Track | External finding and current-code evidence | Disposition / initial priority | Completion state |
| --- | --- | --- | --- |
| R1 / F1 | Meaning-changing claims reportedly pass through `/ask`. `generation._verify_text` still uses term overlap, numbers, quotes and negation; generated lead-ins still say sources support the answer. The research template still says “Verified synthesis.” | High: reproduce; correct confidence contract and source inspection. Measure semantic quality separately. | Portable packet prepared; integration and acceptance open |
| R2 / F2 | A stamped scan reportedly skips OCR and misses a known term. `PilotStore` PDF extraction still selects expanded OCR using a text-strength threshold of 20 and counts nonempty units as searchable pages. | High: reproduce; correct OCR selection and coverage reporting. | Portable packet prepared; integration and acceptance open |
| R3 / F4 | Unset auth reportedly allows passwordless preview access over a container network. Identity and app factories still default to preview; CLI container binding does not check auth mode. Installer doctor does not compare effective auth mode. | Prompt security hardening: verify entry points and impact, then fail closed for installed service operation. | Portable packet prepared; integration and acceptance open |
| R4 / revised F5 | Source control characters reportedly cause a case-note 500, report rejection, and repeated answer failure. `_safe_text` rejects controls; `save_support_notebook` catches `KeyError` but not `WorkspaceProblem`; DOCX serialization only XML-escapes text. | Medium: reproduce save failures; define provenance-preserving text handling and serializer defense. Reachable DOCX corruption is not established. | Portable packet prepared; integration and acceptance open |
| R5 / F3 | Scheduled purge is deliberate. Current maintenance calls `purge_due_matters`; architecture documents a temporary workspace. The review corrected its lifetime claim: the extension horizon rolls forward. | Policy decision plus recovery investigation. Missing automatic export is not itself a defect. | Portable packet prepared; integration and acceptance open |
| R6 | A reported account-cache timestamp test fails on overlayfs but passes on tmpfs. | Security-relevant investigation: determine whether stale authorization is reachable on a supported filesystem. | Actual-writer tests prepared; filesystem comparison and impact open |

## Packet receipts and integration order

All seven heads below have passing branch-push and pull-request Quality runs,
including application, PostgreSQL, synthetic-browser, transcription, deployment,
publication, secret and scope checks. Pull-request runtime jobs exercise GitHub's
integration candidate; publication scanning binds to the PR head. Each also has a
completed code review for its recorded head. The audit identified a final-head
research-presentation finding in #110, corrected by the follow-up in this packet.
Five earlier #113 discussions were reconciled and resolved after checking their
fixes; a completed review alone does not mean all findings are cleared.
These are standalone receipts, not an integrated-product result. Earlier failed,
timed-out or incomplete attempts and native-platform limitations remain in each
PR; a passing later run does not turn those attempts into passing evidence.

The initial policy bot approvals used the optional-review mode. They did not prove
completed code/security review or independent maintainer acceptance. All seven
PRs now carry `require-hosted-review` while remaining draft with auto-merge off.
This correction integration enforces the maintainer's stricter requirement: final-commit hosted
code review plus security review (or the documented verified security-quota
exception), reconciled findings, required CI and later full-head maintainer
acceptance. In
particular, #115's security request has no verified security-specific completion;
a generic clean code-review reply is not that receipt and proves no quota exception.

The renewed review also identified a #113 resource-bound follow-up: tab-heavy
DOCX content must be bounded before serialized XML/run expansion. That correction
requires its own regression and fresh candidate validation.

Integration review also identified two #115 follow-ups: apply the source-text
presentation policy to fetched excerpts without changing exact JSON/digests, and
hold the existing response lease through the final HTML/JSON body byte so matter
purge cannot overlap delivery. Both require synthetic regressions and renewed
final-head evidence; the standalone #115 receipts below predate these corrections.

Feature-document links outside this packet use immutable PR-head permalinks until
the corresponding change is merged.

- **[#110](https://github.com/neilofneils404/recordbench-oss/pull/110) — R1a.1 confidence presentation.**
  Known historical/current answer presentation, synthesis wording and Report-copy cautions; semantic verification is unchanged.
  Head: `e7e38b2eebc0c6fab8890effa22c6c3f14051790`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35851940103);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35851944311);
  [generated-answer review](GENERATED_ANSWER_REVIEW.md). The follow-up correction
  in this packet normalizes matching historical research introductions across
  views, per-search findings, exports and new Report copies while retaining saved
  records. Its fresh review and CI must replace the earlier-head receipts before merge.

- **[#111](https://github.com/neilofneils404/recordbench-oss/pull/111) — R5 retention/recovery.**
  Serializes purge, work admission, extension and retry checks; includes synthetic clean-restore evidence and an expired-matter recovery runbook. Retention policy is unchanged.
  Head: `1c86f96d5f4027e56f0705b9a15af618a557f16d`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35853955393);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35853961013);
  [expired-matter recovery](https://github.com/neilofneils404/recordbench-oss/blob/1c86f96d5f4027e56f0705b9a15af618a557f16d/docs/EXPIRED_MATTER_RECOVERY.md).

- **[#112](https://github.com/neilofneils404/recordbench-oss/pull/112) — R3/R6 authentication/cache.**
  Requires explicit auth, restricts preview/test access, checks effective installed mode, and exercises actual account-writer changes. Overlayfs/tmpfs and installed providers remain open.
  Head: `0534e5c1a508d916d667588ad9886b0292e02702`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35852516468);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35852585836);
  [authentication diagnostics](https://github.com/neilofneils404/recordbench-oss/blob/0534e5c1a508d916d667588ad9886b0292e02702/docs/AUTHENTICATION_DIAGNOSTICS.md).

- **[#113](https://github.com/neilofneils404/recordbench-oss/pull/113) — R4 source controls.**
  Preserves source snapshots while projecting unsupported controls safely for derived prose and readable exports; handles older saved data. Versioned TXT extraction remains open.
  Head: `ae7e6d370bf7d19d8ea7ad81ebc4317e963cde40`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35858843237);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35858849986);
  [source-text presentation](https://github.com/neilofneils404/recordbench-oss/blob/ae7e6d370bf7d19d8ea7ad81ebc4317e963cde40/docs/SOURCE_TEXT_PRESENTATION.md).

- **[#114](https://github.com/neilofneils404/recordbench-oss/pull/114) — R2 PDF OCR/coverage.**
  Uses bounded image evidence for OCR selection and carries incomplete-extraction cautions through current/historical views and exports without replacing old citation bases.
  Head: `4c359d8d17336515c8e2da888bdf45bc444a8fdf`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35857450513);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35857455322);
  [PDF OCR coverage](https://github.com/neilofneils404/recordbench-oss/blob/4c359d8d17336515c8e2da888bdf45bc444a8fdf/docs/PDF_OCR_COVERAGE.md).

- **[#115](https://github.com/neilofneils404/recordbench-oss/pull/115) — R1a.2 cited excerpts.**
  Adds authorized exact-citation comparison for saved focused-answer claims and limitations, including a no-JavaScript page. Broader investigation/synthesis/export comparisons remain open.
  Head: `b02f678cc522f923e0fc8bfb436065174a414ed5`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35867968552);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35867975537);
  [cited-excerpt comparison](https://github.com/neilofneils404/recordbench-oss/blob/b02f678cc522f923e0fc8bfb436065174a414ed5/docs/CITED_EXCERPT_COMPARISON.md).

- **[#116](https://github.com/neilofneils404/recordbench-oss/pull/116) — R1b evaluation harness.**
  Freezes 11 synthetic packets and 27 labeled candidates; separates injected verifier probes from real-model capture and independent human grading. No real-model acceptance is established.
  Head: `7ac28c4c0c3ccd76af61e529f31c87bf0e9fcc81`.
  [Push Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35858146179);
  [PR Quality](https://github.com/neilofneils404/recordbench-oss/actions/runs/35858152957);
  [claim evaluation](https://github.com/neilofneils404/recordbench-oss/blob/7ac28c4c0c3ccd76af61e529f31c87bf0e9fcc81/docs/CLAIM_EVALUATION.md).

Proposed sequential merge order: **#112 → #111 → #110 → #113 → #114 → #115 → #116**.
Establish auth and lifecycle boundaries first, then common answer presentation,
source-text projection, PDF extraction coverage, cited-context comparison and the
evaluation harness. Recheck factory/test callers after #112; worker admissions
and storage locks after #111; historical views, exports and citation provenance
across #110/#113/#114/#115; and production generation behavior with #116. This
order is a review plan, not permission to skip any unresolved gate.

After every protected merge, verify remote main, the merged PR and ancestry before
updating the next branch. A changed head/base requires validation of the resulting
candidate and renewed required review evidence. Preserve each PR as a separately
reviewable change; do not combine the seven into an unreviewed composite merge.

The frozen acceptance pack overlaps #110, #114 and #115. Their standalone receipts
retain the same case definitions, selected node IDs and synthetic fixture bytes;
#114 changes its selected OCR node for the typed outcome and coverage assertions.
Before refreshing combined test-file/node digests and the aggregate fingerprint,
review the resulting test definitions and fixture bytes. Never resolve a digest
conflict by choosing one branch's fingerprint or blindly rehashing altered cases.

## Execution sequence

1. **E0 — Establish reproducible evidence.** Acquire and inspect the external
   scripts/logs outside the tracked tree, or recreate minimal synthetic cases.
   Verify their baseline, fixture provenance, commands and stand-ins. Import only
   reviewed, portable fixtures and regressions. Record a failing-before result on
   the actual candidate for each claimed defect. Preserve unrelated work.
2. **R1a and R3 — Immediate trust and access corrections.** Correct misleading
   confidence language with reachable source inspection; close installed-service
   auth fallback after the configuration matrix establishes the intended boundary.
   Neither depends on GPU availability or a new verifier model.
3. **R2 and R4 — Extraction and saved-work corrections.** Complete each as its own
   reviewable change. Coordinate ownership of ingestion code and citation contracts;
   do not combine text normalization and OCR changes into an unexplained rewrite.
4. **R1b, R5 and R6 — Evaluation and decisions.** Exercise the real model on a
   versioned challenge set, decide retention after reviewing workflow needs, and
   resolve the cache/restore investigations. Start investigation earlier if access
   allows; confirmed security or data-loss defects move ahead of feature work.
5. **E1 — Integrated installation acceptance.** Validate the combined candidate
   through CPU, GPU and applicable recovery lanes below. Record any outstanding
   lane explicitly rather than marking the whole plan complete.

Use one bounded patch per independently reviewable outcome. Product corrections
take precedence over new synthesis/graph features, but this plan does not authorize
deleting those features, broad refactoring, changing model defaults, or weakening
review gates. UI wording/source excerpts must be coordinated with any concurrent
usability work; do not overwrite its templates or styles.

## R1 — Honest answer confidence and inspectable sources

- **R1a.1: confidence presentation** — portable packet in #110; integration
  corrections and final-candidate acceptance remain open. See
  [generated-answer review](GENERATED_ANSWER_REVIEW.md). The follow-up correction
  in this packet normalizes matching historical research introductions across
  views, per-search findings, exports and new Report copies while retaining saved
  records. Its fresh review and CI must replace the earlier-head receipts before merge. Preserve claims, stored
  provenance and reviewer decisions while warning readers in historical/current
  views and exports.
- **R1a.2: excerpt comparison** — focused-answer packet in #115; broader
  investigation/full-text synthesis and excerpt/export comparisons remain open.
  Resolve bounded context from authorized exact references without duplicating
  full source units in saved payloads or bypassing source-version checks.
- **R1b: model evaluation** — portable harness and frozen rubric in #116;
  real-model, learned-retrieval, offline, hardware and human-rubric acceptance
  remain open. Neither the harness nor R1a establishes semantic verification.

**Inspect:** `src/case_intelligence/generation.py`, its callers including synthesis,
answer rendering, `templates/workbench_research.html`, saved conversations, Report
conversion and exports. Start with `tests/test_generation.py` and
`tests/test_answer_jobs.py`; expand by reachable consumer, not wording matches alone.
Preserve Continuity C's additional `_exact_original_span` check for opt-in recorded
context; it is stricter than the normal answer path and does not prove general
semantic verification. Cover both paths and their repair/limitation handling.

**Reproduce:** upload synthetic sources and inject generator responses through the
served workbench answer path. Cover approval/rejection, payer/payee reversal,
cross-source stitching, and loss of uncertainty. Include faithful paraphrase,
low-overlap fabrication, explicit negation, numeric/quote errors, and multiple
citations as controls. Inspect both stored results and what a reader sees.

**R1a correction:** describe deterministic checks accurately; do not imply semantic
verification or human approval. Show exact cited excerpts next to, or immediately
accessible from, each claim, with source identity and locator. A displayed excerpt
is cited context, not automatically a supporting sentence. For multiple citations,
show the relevant excerpts separately. Preserve hedges and conflicting evidence.
Apply the same confidence distinction to saved results, synthesis, Reports and
exports; retain historical source basis and reviewer decisions.

**Acceptance:** all four adversarial cases are either rejected or clearly presented
as unverified generated claims requiring source review, never as established facts.
The source contrast is inspectable in the real browser and applicable exports.
Correct paraphrases remain usable. Existing authorization, citation validation,
coverage notices and source-change handling continue to pass. Regression tests
must exercise outcomes; replacing one string alone is insufficient.

**R1b evaluation:** freeze a synthetic challenge set and grading rubric before
running the installed generator, embedding and reranking stack. Record exact model
revisions, prompt/configuration, seeds where supported, and repetitions. Report
generation error separately from verifier false acceptance and false rejection;
include denominators and case-level evidence. Set any release quality threshold
before inspecting results. Do not call the challenge set a production error rate.
Any new semantic verifier or model change needs its own license, offline readiness,
resource and representative evaluation evidence. R1a can be accepted as a mitigation
while R1b remains open; it cannot be recorded as semantic verification solved.

## R2 — Stamped scans and truthful extraction coverage

**Inspect:** `src/case_intelligence/pilot_uploads.py`, PDF extraction metadata,
source registry/index projections, exact search, answer/full-text coverage, and
`tests/test_upload_pilot.py` plus downstream coverage tests.

**Reproduce:** ingest an actual synthetic PDF containing native text, a full-page
scan with a long stamp text layer, a short-stamp scan, and an image-only page.
Use unique known body terms and real bounded OCR, then check page text, exact
search, readiness UI and source viewer. Add mixed native/image regions, logos,
blank pages, rotated pages, existing good OCR, OCR timeout/failure and cap exhaustion.

**Correction:** use bounded page/image evidence as well as extracted-text strength
to select OCR candidates. Design the text-selection or combination rule before
implementation: longer text alone does not establish better extraction. Preserve
valid native text, page locators, originals and extraction provenance; avoid
duplicated text and accidental loss of stamps or body content.

Represent native extraction, OCR attempted/succeeded/failed, skipped limits and
unknown coverage sufficiently to distinguish “searchable text exists” from “all
page content was read.” Carry gaps into Sources, zero-result searches, questions,
full-text review and exports. No heuristic establishes perfect OCR completeness.

**Acceptance:** the stamped body term is found through real ingestion/search;
good native text and citations remain correct; cap/failure cases have visible
coverage gaps. Compare extraction time and resource bounds against the same fixture
set before/after. Test restart and reprocessing. Specify how old sources gain new
coverage information: never silently replace the extraction behind saved citations.
Version/invalidate derived indexes and saved references as required. Any durable
schema/storage change requires backup and clean restore before acceptance.

## R3 — Fail closed in installed authentication

**Inspect:** `identity.py`, the workbench CLI and application factory, Compose
environment defaults, `scripts/recordbench_install.py`, doctor/update/resume,
and local/OIDC/Kerberos authentication tests.

**Reproduce:** from a separate client exercise unset, empty, invalid, preview,
test, local, OIDC and Kerberos configurations; distinguish loopback development
from installed/container operation. Cover CLI and direct application entry points,
fresh install, manual restart and update/resume. Check unauthenticated reads,
identity selection and mutations, CSRF, and matter isolation. Report impact
separately from the likelihood of operator misconfiguration.

**Correction:** require an explicit production auth mode for installed service
operation, including container binding. Development/test bypass must remain
deliberate and unable to become a network-accessible installed fallback. Choose
the enforcement point after tracing every supported launch path. Doctor should
compare expected and effective mode and fail on mismatch without printing secrets
or expanding unauthenticated health disclosures. Do not replace authentication
with a trusted-network assumption or weaken trusted-proxy validation.

**Acceptance:** the network reproduction fails closed for unsafe installed modes;
supported authenticated modes and explicitly isolated development tests still work.
Missing settings cannot create identities or matters remotely. Synthetic browser
sign-in and relevant provider contracts pass on the final candidate. Real provider
acceptance remains a separate installed-node requirement where applicable.

## R4 — Source controls, safe saves and valid exports

**Inspect:** ingestion and persisted passages, `_safe_text`, notebook/Report save
handlers, generation persistence, and `work_product_exports.py`. Begin with
`tests/test_matter_notebook.py`, `tests/test_saved_answer_report_support.py`,
`tests/test_work_product_exports.py` and answer-job tests.

**Reproduce:** admitted synthetic TXT/CSV/email passages containing XML-forbidden
controls, including SUB and ESC; contrast tabs, newlines, form-feed handling and
ordinary Unicode. Trace search → source save, quoted/paraphrased answer → save,
Report creation and all relevant exports. Include older persisted passages.

**Correction:** preserve original bytes/digests. Define a shared, explicit policy
for derived text and presentation, including control replacement, source locators
and normalization provenance. Do not concatenate words by silently deleting
separators, strip all Unicode formatting indiscriminately, or rewrite historical
citations in place. New-ingestion normalization alone cannot repair existing data.
Catch expected validation exceptions and give a useful recovery path rather than
500 or an endless retry suggestion. Apply XML-valid character handling at the
serializer boundary; ordinary entity escaping is not sufficient.

**Acceptance:** valid synthetic passages remain searchable and can be saved with
traceable originals. Unsupported cases receive a controlled, actionable response
without losing a draft. Parse generated DOCX XML and inspect rendered output for
answer, conversation, notebook, Report, bundle, every-source, investigation and
full-text paths that include these passages. Preserve meaning and attribution,
not merely XML well-formedness. Prove existing-data behavior and backup/restore
if persistent text or storage representation changes.

## R5 — Retention policy and recovery safety

**Review:** current creation defaults, rolling extensions, warnings, owner/admin
authority, active-work deferral, purge, manual close and audit retention using
`tests/test_matter_retention_and_themes.py` and backup/closure tests.

Reproduce warnings/grace/purge with a controlled clock and synthetic matter.
Confirm unmanaged originals stay outside deletion. Test extension versus purge,
work finishing during purge, restart, and late workers attempting to save.
Restore an expired synthetic matter into an isolated target with maintenance held
until inspection; then deliberately test maintenance activation and document the
outcome. The #111 synthetic drill confirms that restore preserves expired
deadlines and the first enabled maintenance pass can purge them immediately;
this is existing retention behavior, not a new policy choice. Include current
Continuity B/C selection and request-receipt state (migrations
0035/0036) in complete-runtime restore and purge checks. Use the matching reader;
never validate rollback by opening upgraded stores with the older local checkout.

**Decision required before policy implementation:** temporary review workspace
versus ongoing case workspace; safe default, extension authority, warning delivery,
and whether scheduled deletion requires confirmation. Compare retaining the current
policy with stronger warnings, opt-in automatic expiry, and no automatic expiry.
Record the chosen outcome and upgrade treatment for existing matters.

Do not automatically write a final bundle as a presumed fix. If selected, define
its authorization, destination, encryption, retention, capacity, failed-export
behavior and eventual deletion; a bundle is not an importable node backup.

**Acceptance:** documented policy and UI match, existing-matter transitions are
explicit, irreversible actions are predictable, and the synthetic recovery drill
does not destroy restored work before operator inspection. Any confirmed recovery
defect gets a bounded correction independently of the broader policy decision.

## R6 — Account cache and filesystem behavior

Reproduce the reported metadata-granularity failure with the actual account writer
and supported storage layouts. Test rapid password, role and enabled-state changes,
including same-size replacement, and ensure old sessions cannot retain revoked
authority. A test passing on tmpfs does not settle behavior on other filesystems.
Classify setup defects separately from reachable stale authentication; fix the
latter promptly if established, preserving bounded account reads and locking.

## Validation lanes and acceptance record

| Lane | What it establishes | Required evidence / limitations |
| --- | --- | --- |
| Local development / isolated Linux VM | Deterministic failures, synthetic HTTP workflows, controlled model outputs, focused regressions | Record OS/architecture, packages, stand-ins and all failed/skipped checks. No GPU or installer readiness claim. |
| Exact-candidate hosted Linux CI | Portable regressions and applicable application, PostgreSQL, browser, deployment and transcription contracts | Record full candidate SHA and actual jobs run. Docs-only skips and parent-commit results are not candidate runtime acceptance. |
| Clean x86-64 Linux CPU installation | Public installer, effective auth, real scanner/OCR, browser → intake/search/save/export, update/restart and diagnostics | Use the public playbook and synthetic data, adequate disk and normal reserve. No mocked scanner or manual environment presented as installer proof. |
| Installed review/GPU profile | Real embedding, reranking and generation behavior, R1b grading, coverage propagation and bounded resources | Exact candidate, model revisions/license records, GPU/VRAM/driver/runtime and synthetic workload; verify offline operation. No extrapolated production accuracy or throughput. |
| Recovery and applicable full profile | Consistent backup, clean restore/rollback, expired-matter handling; transcription/media smoke when affected | Separate original/source state from rebuildable projections. Restore only to isolated targets. Real media/model acceptance is not inferred from a document-only run. |

The installed-node lane uses a separately authorized, isolated validation target;
do not operate an existing deployment or import its state to satisfy this plan.
Where hardware is unavailable, complete portable corrections and explicitly leave
GPU acceptance pending. Model or deployment changes require the applicable lane
before their readiness claim. These receipts do not supersede release readiness.

For each packet, record: owner; full baseline/candidate SHA; fixture version/hash;
commands and environment; expected/actual behavior; failing-before/passing-after
evidence; executed/skipped/failed checks; changed user outcome; migration/rollback;
remaining uncertainty; and reviewer disposition. Use statuses **open → reproduced
→ corrected → locally validated → CI validated → installed acceptance**, with
separate flags for GPU acceptance and policy decisions. “Mitigated” is not “solved.”

Test failures need a specific cause and evidence. Storage-reserve-disabled reruns
are diagnostics, not normal-capacity acceptance. Do not disable the reserve on an
installed node to obtain a green result. Do not waive filesystem failures merely
because another filesystem passes. Run appropriate required suites on the final
combined candidate; do not repeatedly rerun unrelated suites without a reason.

Before any authorized publication, run the installed pre-push publication guard
and separately inspect report text, fixtures and artifact metadata. Follow the
current upstream [public-alpha](PUBLIC_ALPHA.md) policy: Quality and branch
protections always apply; hosted review is optional unless `require-hosted-review`
is enabled. Strict opt-in requires final-head code/security review, reconciliation
and maintainer acceptance. Honor any additional review requirements explicitly
set by the maintainer for this work. Do not change review policy as part of these
fixes. Each implementation section must have its own reviewed change and receipt;
tracking an issue or publishing a draft PR does not establish acceptance.

## Remaining acceptance and receipt maintenance

- **R1a:** finish integration corrections and validate historical/current answer,
  investigation and synthesis presentation. The focused-answer comparison packet
  does not complete broader investigation/full-text synthesis or export comparison
  surfaces. Preserve exact cited context and source authority when combining it
  with control-character presentation.
- **R1b:** run the real generator and learned retrieval components on an authorized
  isolated target, with exact revisions/licenses, offline and hardware evidence,
  independent human rubric approval and preregistered release thresholds. The
  frozen injected probes report verifier behavior only, not generation quality.
- **R2:** representative recognition quality and clean installed CPU acceptance
  remain open. The Mac real-tool probe substituted executable paths and an
  unsupported resource limit. An upside-down page was selected but incorrectly
  recognized; selection and preserved stamps do not establish rotated-scan quality.
- **R3/R6:** clean installed Linux/container and applicable provider acceptance,
  plus the reported overlayfs/tmpfs comparison, remain open. Actual-writer tests
  did not reproduce stale authority on APFS; that does not resolve other filesystems.
- **R4:** versioned TXT extraction/reprocessing remains a separate follow-up.
  Existing `splitlines()` interpretation and saved source bases are preserved.
  Synthetic restore and DOCX rendering evidence do not establish full-node recovery
  or Microsoft Word acceptance.
- **R5:** retention defaults, rolling extensions, warning delivery, deletion
  confirmation and any automatic-export/backup policy remain explicit product
  decisions. Synthetic clean restore covers the portable correction; encrypted
  replacement-host recovery, real PostgreSQL backup import and installed acceptance
  remain separate. A restored expired deadline is preserved, so hold maintenance
  for inspection as the recovery runbook requires.

Keep #109 open. After each merge, add its verified resulting main commit and exact
review/CI receipts, distinguish merged code from remaining product acceptance,
and recheck links and the next branch's base. Update this plan through reviewed
changes; never pre-record a future merge or reuse these standalone receipts as
proof that a later integration correction passed.
