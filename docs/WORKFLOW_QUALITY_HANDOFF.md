# Pump Cedar workflow quality evaluation

Public baseline: `d43e142769b5d57a901fb58439bf841ed954b8b4`.
This companion evaluates the lower-priority quality observations from a sanitized
workflow handoff. All source wording is newly authored fictional material. It
does not import original audit material or qualify a deployment.

## Findings

| Observation | Public-baseline classification | Evidence and remaining limit |
| --- | --- | --- |
| Full-text processing missed relevant evidence | Needs more evidence for learned-model recall | Real file ingestion, every resulting source packet, persisted review decisions, full-text coverage, original-source routes, JSON export and a stale human save are checked with a controlled classifier. All four relevant sources are included and the control excluded under declared positive outcomes. A separately injected maintenance miss also finishes with complete coverage, but gold recall is 3/4. This proves coverage is independent of recognition; it does not reproduce a learned classifier miss. |
| Follow-up repeats observations instead of addressing uncertainty | Needs more evidence for semantic usefulness | The fixed rubric distinguishes concern, action, undocumented confirmation, observation limits and compatible corroboration. A controlled response keeps supported uncertainty, collapses an exact duplicate, and rejects an invented purchase-order claim with an omission notice. No learned follow-up or hierarchical synthesis quality score is claimed. |
| Repetitive synthesis | Partially bounded by existing exact-duplicate behavior; semantic problem needs more evidence | Current grounded-answer parsing coalesces an identical claim in the new boundary test. Paraphrased redundancy, meaningful disagreement retention and overall draft usefulness require independent rubric review of actual generated results. |
| Excessive discovery inventory | Reproduced as occurrence-level suggestions, not an adjudicated entity count | Five synthetic sources yield ten suggestions: three Pump Cedar mentions, three copies of one date, two similar but distinct device labels, and two different date labels. There are six distinct labels. Original offsets/version/text references remain exact; matching candidates are offered for review, a manual merge moves both mentions and Undo restores them. No automatic reconciliation change is made. |

The production classification prompt instructs the model to satisfy every
required checklist element. The handoff criterion is disjunctive: discrepancy,
related maintenance **or** resolution evidence. This is a plausible diagnostic
lead, not evidence that the prompt caused a miss. The fixture intentionally
retains the criterion unchanged and supplies no extra include/exclude guidance.
Do not change the prompt until actual output demonstrates the failure and a
bounded correction passes the negative and uncertainty controls.

Coverage UI and JSON exports already state that completion does not establish
recognition of every relevant fact. The new tests read those surfaces and show
that a human override does not rewrite the machine outcome, rationale or cited
support. A stale override is rejected and the accepted note remains intact.
These checks qualify current-state separation and stale-save protection, not a
complete append-only history of every earlier human note. The current
`adjudicate_review_decision` updates the live human decision row; no schema or
storage change is included in this evaluation.

Exact source text can also encounter the existing answer verifier's conservative
multi-sentence negation rule: a paragraph combining the readings with “not yet
established” can be rejected when its best-overlapping source sentence has no
negation. The positive boundary fixture uses independently supportable sentences
as required by the answer contract. This is a verifier diagnostic requiring
separate evaluation, not evidence that any particular model emitted that
paragraph or that rejected claims should be admitted without verification.

## Fixed gold and scoring

`case_intelligence.workflow_quality_gold` contains 30 source cases: the five
handoff sources under six labeled conditions (baseline, identifier variation,
paraphrase, transcript wording, placement on late pages, and repeated support).
There are 24 gold-relevant cases and six unrelated controls. Each label has a
written reason independent of the classifier. The suite fingerprint is
`56a5bca6a2e7d7d9b05331b25e97432a854731d18cdb4c237b2bfca2366740aa`.

This is a broader challenge matrix than the five-source acceptance case, but
it is still variants of one matter. It is not a representative domain sample.
Do not treat correlated variants as independent samples for confidence intervals
or infer production precision/recall from their scores.

The scorer reports precision, conservative recall, conditional recall, false
negative IDs, unresolved IDs and unresolved relevant IDs. Missing/rejected
decisions count against conservative recall and never disappear from the gold
denominator. Conditional recall is labeled separately so unavailable work cannot
make an apparent recall pass. There is no percentage when its denominator is
zero. Metrics from deliberately controlled outcomes test this accounting only.

The semantic rubric has seven independently reviewed dimensions: initial
concern, later action, unverified confirmation, observation limits, agreement
and conflict, consolidation, and unsupported premise. Score each 0 (wrong or
missing), 1 (partial), or 2 (clear and correct), with a short rationale and cited
originals. A small-fixture semantic pass requires 2 on every applicable dimension,
zero invented facts/citations, and all required supported facts retained.
Do not use exact-prose matching or the evaluated model as the sole judge.

## Reproduction and continuation

Create fresh reviewable text files and a gold manifest without inference:

```console
python scripts/evaluate-workflow-quality.py --write-corpus /tmp/pump-cedar-quality-new
```

The output directory must be new. No binary media is committed. The pytest
fixture separately generates searchable PDFs, including a 15-page comparison,
and reads extracted text before any decision. The recollection is plain text in
that full-text test: it does not qualify transcription or media navigation.
Timestamped media and mixed Report support require the separate workflow repair
checks. The evaluator labels recollection packets as transcript evidence for the
grounded-answer boundary but does not pretend to have transcribed a recording.

On a prepared Linux development environment, run the unmodified tests:

```console
PYTHONPATH=src python -m pytest -q tests/test_workflow_quality_handoff.py
PYTHONPATH=src python -m pytest -q tests/test_full_text_review.py tests/test_review_decision_conflicts.py tests/test_entity_discovery.py tests/test_generation.py tests/test_review_acceptance_pack.py
```

Native macOS results on the public baseline: the five non-PDF checks passed;
the generated PDF library extraction check also passed. Both PDF workflow
parameters hit the existing child-process `RLIMIT_AS` limitation before PDF
extraction. With an external, process-local test adapter that runs the unchanged
PDF child helper while bypassing only its unsupported native `RLIMIT_AS` call,
all eight new tests passed. Its remaining subprocess limits and actual `pypdf`
extraction remain active. That adapter changes no repository file and is not
Linux extraction-isolation evidence. The checked-in tests contain no host skip;
Linux must run them without the adapter. The fixture's PDF font explicitly uses
WinAnsiEncoding to preserve the newly authored apostrophe text on extraction.
The five existing focused modules in the second command passed all 83 tests on
native macOS. Changed Python files compiled and the content-only publication
sanitizer reported clean; history publication and complete contributor gates
remain the integrating change's responsibility.

For actual model evaluation, first identify an already available, approved local
Ollama model and its immutable digest. The runner requires every parameter and
refuses a different artifact, a non-loopback endpoint or an existing output file:

```console
python scripts/evaluate-workflow-quality.py \
  --endpoint http://127.0.0.1:11435 \
  --model APPROVED_MODEL \
  --expected-digest APPROVED_SHA256 \
  --output /tmp/pump-cedar-model-results-new.json
```

It never downloads or starts models. It uses the application classifier and
grounding verifier on every authored packet, aggregates source outcomes, retains
packet rationales and failures, and runs the supplied follow-up plus the
unsupported purchase-order question. It records revision, dirty-tree status,
model digest, fixture fingerprint and unscored semantic rubric. Its current
boundary is authored packets, not a complete ingestion/browser/hierarchy run.
The approved local generator was unavailable during this evaluation; **no actual
model precision, recall, follow-up usefulness or synthesis score was produced**.

Before claiming model quality, extend the gold with independently authored
matters and adjudicated labels, run the actual workflow on extracted originals,
inspect false negatives and rationales, score the semantic rubric independently,
and report both machine and human decisions separately. Retain failures,
unavailable units, omission notices, configured limits and model metadata. A
passing five-source or 30-source fixture does not complete that qualification.
