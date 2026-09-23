# Reviewing generated answers

Generated answers and synthesis are drafts for source review. Citation references,
word overlap, quoted-text checks and numeric/negation checks do not establish
that a sentence preserves the meaning of its source. A claim can reuse source
words while reversing a decision, swapping participants, combining unrelated
details, or dropping uncertainty.

New focused answers are introduced as generated work for source review. The Case
conversation, assistant panel, and synthesis view warn that automated checks do
not establish correctness. Known older answer introductions receive current
confidence language when displayed or exported; their saved payload, claim text,
source identifiers, and reviewer history are not rewritten. Word and Markdown
answer/conversation exports carry the notice, as do synthesis exports; portable
conversation and investigation JSON expose a review notice. Reports retain their
existing instruction to verify statements against original sources.
Saving a generated answer to a Report also normalizes its leading introduction
and includes the generated-text review notice in the new section and its exports.
The original saved message remains unchanged.

Portable conversation JSON updates both the structured introduction and the
matching leading introduction in the full generated message text. It does not
replace quoted occurrences inside claims or alter user-authored messages. Research
instructions and progress describe citation/text checks, not verified meaning.

Use each claim's citation to open the source and compare the wording, participant
roles, qualifications and surrounding context. Multiple citations do not establish
that their details belong to the same event. For transcripts, check the recording
and speaker attribution too. The recorded-context answer path retains its extra
original-span checks; those checks also do not establish general factual truth.

This is the first R1a mitigation in the [review correction plan](REVIEW_CORRECTION_PLAN.md),
tracked in [issue #109](https://github.com/neilofneils404/recordbench-oss/issues/109).
It does not change the generator, verifier acceptance algorithm, citation basis,
or storage schema. Direct inline excerpt comparison and real-model evaluation
remain separate open sections. Saved research summaries and human-authored text
remain historical content; the surrounding review notice is current presentation.

## Synthetic regression

`tests/test_generated_review_confidence.py` supplies four meaning-changing outputs
to the generator boundary and checks that any accepted result is presented for
review. A future verifier may reject them without breaking this contract. Faithful
paraphrase and fabricated-detail controls check continued usability and rejection.
HTTP rendering and Word/Markdown exports check historical answers without mutating
their stored payloads. These are deterministic software checks, not a measurement
of the installed model's error rate or GPU acceptance.
