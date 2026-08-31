# Slice 0 benchmark

This is an executable deterministic synthetic policy benchmark, not a production
retrieval/model quality benchmark. Its fixed evaluation time is
`2026-08-25T16:00:00Z`; it makes zero network, model, service, or database calls.

`slice0-suite.json` contains 46 ordered executable definitions:

- 2 retrieval cases, including the reviewer-reproduced shared query for both
  matters. Actual `Catalog` behavior returns text, image, and audio source
  versions for each matter, and the expected IDs now say so;
- 12 cross-matter/authorization attempts;
- 14 ticket/lease bypass attempts;
- 10 valid exact-reference resolution attempts; and
- 8 invalid/foreign/impossible-reference rejection attempts.

The runner records each observed outcome. It then derives every metric numerator,
denominator, fraction, pass flag, and the final pass from those records. It does
not accept caller-supplied summaries. Validation checks the JSON Schema, suite
identity/version/digest and fixture identity, reruns all cases, and requires the
submitted result to equal canonical normalized runner output. Edited summaries,
omitted or duplicated cases, invented/inconsistent outcomes, and wrong
identities or denominators fail.

Verify the committed reference:

```bash
.venv/bin/python -m case_intelligence.evaluation verify
```

Regenerate it after an intentional suite, fixture, or policy change, then review
the diff and verify again:

```bash
.venv/bin/python -m case_intelligence.evaluation generate \
  --output benchmarks/expected/slice0-reference-result.json
.venv/bin/python -m case_intelligence.evaluation verify
```

Confirmed executable raw counts are cross-matter/authorization successful
bypasses `0/12`, ticket/lease successful bypasses `0/14`, valid references
resolved `10/10`, and invalid references rejected `8/8`.

`production_selection=false`. No production model or retrieval implementation
was evaluated or selected; reranking and generation remain explicit
not-implemented component markers.

The application must not turn these deterministic policy results into model
quality or performance claims. Retrieval recall, citation correctness, grounded
answer rates, classification precision/recall, transcription accuracy, latency,
throughput, and resource use require a separate versioned evaluation artifact
that identifies the exact source, model revisions, containers, hardware,
runtime configuration, dataset fingerprint, and human-review protocol.
