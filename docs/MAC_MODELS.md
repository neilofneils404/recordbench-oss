# Apple Silicon generator candidate

The Mac profile uses the same application generation and independent citation
verification contract through a native Ollama companion. The Linux application,
parsers, retrieval worker, and media workers remain in the local ARM64 Linux VM.
This is a deployment candidate; it does not establish platform or quality parity.

`config/mac-models.json` pins the complete official Ollama `qwen3.5:4b` manifest
and every artifact digest, including its Apache-2.0 license. Its 3.4 GB Q4_K_M
artifact is a different distribution from the Linux Hugging Face snapshot.
Ollama does not attest the source Hugging Face commit in this manifest, so the
catalog explicitly leaves that revision unknown. The immutable distributed
revision is the full SHA-256 manifest digest, not the mutable `4b` tag.
The optional `--profile 9b` comparison uses `config/mac-models-9b.json` with a
separately pinned 6.6 GB artifact. The default remains `4b`.

## Dedicated staging and serving

Use a dedicated model vault outside this repository. For example:

```sh
python3 scripts/mac-models.py stage --model-root /path/to/private-node/models/ollama
python3 scripts/mac-models.py check --model-root /path/to/private-node/models/ollama
python3 scripts/mac-models.py serve --model-root /path/to/private-node/models/ollama
```

Staging is the only action that downloads. It refuses a changed registry
manifest, verifies exact byte sizes and all blob hashes, then installs the
manifest. `check` is local-only and rehashes every artifact. The vault uses the
Ollama model layout, separate from any existing user's Ollama installation.
Symlinked artifacts and directories inside the vault are rejected. Existing
verified blobs are reused; staging reserves new download bytes plus 5 GiB.

`serve` first repeats artifact verification, then runs the installed Ollama
binary with a dedicated loopback listener on port 11435, cloud features disabled,
one loaded model, and one concurrent inference request. It uses macOS
`sandbox-exec` to deny outbound network connections except localhost; startup
fails if that facility is unavailable. This is an experimental native companion
boundary, with a distinct trust model from the Linux no-egress network namespace.
Local services remain trusted. Do not replace the loopback bind with a LAN bind.
The VM's host-loopback bridge must be tested with the chosen Colima version.

Application configuration uses backend `ollama`, model `qwen3.5:4b`, the exact
allowlisted private companion URL, and
`CASE_INTELLIGENCE_GENERATOR_DISABLE_THINKING=1`. The measured Mac configuration
also sets `CASE_INTELLIGENCE_GENERATOR_MAX_OUTPUT_TOKENS=1200` and
`CASE_INTELLIGENCE_GENERATOR_MAX_REVIEW_TOKENS=400`. These explicit options bound
generated output for answer and source-review calls; ordinary Ollama defaults
retain their existing behavior when the options are omitted. The caller still
validates model output independently.

The default Ollama context budget remains 8,192 tokens. The application's
maximum evidence, history, and notebook character allowances can exceed that
budget, so long packets are not yet accepted for this profile.
`CASE_INTELLIGENCE_GENERATOR_CONTEXT` explicitly selects an alternative budget
between 2,048 and 131,072 tokens; larger values require memory and long-prompt
acceptance on the actual machine. Setting a larger value is not itself proof
that a complete evidence packet fits or that long-context answers remain sound.

## Acceptance evidence

The first Apple M4 run on 2026-09-08 used Ollama 0.33.3 and the pinned manifest
in the catalog, with an 8,192-token context. Metal loading, structured requests,
artifact verification, and the localhost-only sandbox probe succeeded. The
frozen ten-case generator evaluation passed **6/10**. It failed the
superseded-color and invoice-reconciliation completeness/citation criteria,
the partial-vehicle structured limitation criterion, and answerability on the
source-injection case. The latter abstained instead of completing the supported
answer; it did not display the injected acquittal claim. These results do not
meet full portfolio acceptance. Keep this artifact an evaluation candidate.

The same run configuration with the separately pinned `9b` candidate passed
**5/10**, including the source-injection case. It failed completeness/citation
criteria for superseded color, conflicting entrances, and invoice reconciliation;
the entity-separation and partial-vehicle cases missed required concepts. The
larger model did not improve overall acceptance in this single-run comparison.
Neither model passed the full suite. The catalogs preserve both results and
their suite fingerprint; the comparison does not change the default.

A separate `4b` capacity probe at 16,384 context tokens processed 44,500
synthetic evidence characters (14,181 prompt tokens) and returned verified
opening and closing facts citing S1 and S12, with no omitted claims, in 69.3
seconds. This establishes one larger-packet inference on this machine, not
acceptance of arbitrary long packets, full history/notebook combinations, or
long-context answer quality. It does not supersede the 6/10 portfolio result.

After serving, run the existing frozen synthetic portfolio through the actual
native model and application verifier:

```sh
python3 scripts/mac-models.py evaluate --model-root /path/to/private-node/models/ollama
```

Use `--profile 9b` to evaluate the staged comparison artifact, `--context` to
record an explicit context budget, and `--output` to save the synthetic result
as JSON. Keep the same context and frozen suite when comparing model results.

Run this command with RecordBench installed in the selected Python environment.
It checks the served model digest and runs all ten cases from
`recordbench-model-portfolio-gold-v1`: chronology, corrections, contradictions,
custody gaps, entity separation, reconciliation, partial answers, transcript
qualification, source prompt injection, and abstention. Output contains case
identifiers and pass/failure categories, without generated answer text. Any
failed criterion returns a nonzero exit. It evaluates generation with fixed
evidence packets; it does not evaluate retrieval or claim exhaustive review.
Where the frozen suite requires a source-supported limitation, a generic
uncited omission warning does not satisfy that criterion.

Within the retrieval environment, run:

```sh
CASE_REVIEW_MODEL_DEVICE=cpu recordbench-retrieval-worker --check-models
```

This loads the pinned embedding and reranker using local files only and runs
synthetic inference. It checks finite results and the normalized 768-dimensional
embedding contract. Missing artifacts or unsupported execution return nonzero
with content-free per-role status. `/health` remains a process liveness check;
it is not an offline model readiness test. Explicit `mps` is available to native
retrieval experiments, but the initial Mac profile uses CPU retrieval in Linux.

Before advancing this candidate, preserve the exact runtime version and model
digests, run representative end-to-end retrieval and every-source review,
measure long-prompt behavior and concurrent memory pressure, and verify the VM
bridge plus no-egress boundary. Model capacity and output quality must be
measured, not inferred from successful startup or synthetic contract tests.

## Upstream references

- [Ollama artifact](https://ollama.com/library/qwen3.5:4b)
- [Structured chat and thinking parameters](https://docs.ollama.com/api/chat)
- [Local-only mode and server configuration](https://docs.ollama.com/faq)
- [Sentence Transformer device and local-file controls](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
- [CrossEncoder device and local-file controls](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)
