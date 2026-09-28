# Model choice, acquisition and compatibility

RecordBench's product direction is to let operators select and procure models
compatible with its adapters. The reference configuration gives contributors a
repeatable starting point; it is not an exclusive list of models the product
should ever support. Model selection belongs in administrator configuration,
while reviewers choose capabilities such as transcription or generated answers.

The application remains responsible for access controls, source citations,
exports, job handling and clear failure messages regardless of model choice.
Accuracy and resource requirements depend on the selected models and inputs.

## What can be configured today

| Component | Existing integration | Current limit |
|---|---|---|
| Answer generation | `CASE_INTELLIGENCE_GENERATOR_BACKEND` selects `ollama` or `openai`; `CASE_INTELLIGENCE_GENERATOR_URL` and `CASE_INTELLIGENCE_GENERATOR_MODEL` select an operator endpoint and model | The endpoint/model must satisfy the adapter's request, structured-response and citation contracts. The installer supplies a reference local configuration; an arbitrary compatible-looking API is not automatically qualified. |
| Embeddings | `CASE_REVIEW_EMBEDDING_MODEL` and `CASE_REVIEW_EMBEDDING_REVISION` configure the SentenceTransformer worker | Local files are required; remote model code is disabled. Embedding dimensions, index compatibility and reindexing must be checked before changing a populated deployment. |
| Reranking | `CASE_REVIEW_RERANKER_MODEL` and `CASE_REVIEW_RERANKER_REVISION` configure the CrossEncoder worker | Local files are required; remote model code is disabled. Ranking/output behavior still needs evaluation. |
| Speech recognition | WhisperX/faster-whisper profiles use approved CTranslate2 snapshots | Installed profile-to-repository mappings are currently fixed in `asr_models.py`; there is no complete arbitrary-model import/selection workflow yet. |
| Word alignment | Manifest-approved English/Spanish Torchaudio checkpoints | Language-to-checkpoint bindings are currently fixed. Another language/checkpoint requires adapter and inventory support. |
| Speaker diarization | Nemotron or Community-1 adapter selected during installation | These are separate implementations with their own artifact/runtime contracts. An unrelated diarization model cannot be substituted by changing a filename. |

These are application/worker configuration interfaces, not a claim that the
installer exposes every choice interactively. Review the resolved service
configuration when using an operator-managed deployment. Do not modify the
Python mapping or remove manifest checks merely to make a custom model appear
ready. Adding a new architecture may require a new adapter; a compatible model
should eventually need only an administrator-owned configuration entry.

The current model-portfolio display also assumes reference generator IDs and
retrieval metadata. Configurability of the underlying adapters does not yet
provide complete custom-model installation, readiness reporting or migration.

## What RecordBench distributes or acquires

The source repository and reference model catalog contain configuration and
download references, not the main ASR/generator/embedding/diarization weights.
The installer obtains selected artifacts from upstream into the operator's
model cache. Their terms remain separate from RecordBench's Apache-2.0 license.
Operators should consult the exact upstream model card and terms for their use,
including any required access approval. A download instruction does not grant
additional rights or establish suitability for every use.

Some dependencies contain artifacts inside their packages. In particular,
WhisperX includes a VAD checkpoint. RecordBench preserves its verified MIT
notice in the service package/image inputs; see [third-party notices](../THIRD_PARTY_NOTICES.md).
Describing a deployment as using operator-supplied models does not remove
notices for components actually included in an image or package.

The current alignment preparation also downloads the pinned NLTK `punkt_tab`
resource automatically. Its catalog entry explicitly says
`UPSTREAM-TERMS-REVIEW-REQUIRED`. Upstream lists Punkt resources among those with
[unclarified dataset licensing](https://github.com/nltk/nltk_data/blob/gh-pages/DATASET-LICENSES.md).
This is separate from the NLTK software license. Review that dependency before
selecting alignment; no broad permission or automatic approval is implied.
A clearer resource acquisition/consent flow and local import path are tracked
below. This does not prevent contributing to the source or evaluating workflows
that do not require that resource.

## Reference configurations and operator-selected models

Record a model's role, adapter, upstream identity/revision or local content
digest, file inventory, terms link and acquisition method. Integrity checks
establish which bytes execute; a hash is not a judgment about licensing or
quality. A model supplied by an operator still needs compatible files, enough
resources and an administrator-approved inventory.

Publish observed results for exact reference configurations, with their
limitations. Other configurations can be experimental without pretending that
the project has tested every model. Do not advertise accuracy, hardware minimums
or throughput based only on unit tests or upstream model benchmarks. Preserve
source playback and human review of generated transcripts and answers.

## Focused contribution work

1. Add a versioned administrator model configuration mapping roles/profiles to
   adapter-compatible local artifacts. Replace hard-coded repository bindings
   with validated configuration while retaining hashes, no-symlink boundaries,
   offline loading and profile availability checks. Portfolio/readiness metadata
   must describe the selected configuration. Job requests must not supply
   arbitrary model paths or executable code.
2. Separate acquiring reference artifacts from importing an existing local
   model inventory. Show the selected resources and upstream terms before
   acquiring them; unresolved terms must be explicit. Do not claim a universal
   import command until it exists and has tests. Keep credentials out of
   manifests and logs, and keep runtime inference downloads disabled.
3. Validate two independently constructed compatible synthetic model mappings,
   rejection of incompatible/mutated files, persistence across restart/update,
   unavailable-model recovery and useful user-facing errors. Then run an actual
   reference-model workflow. A new architecture gets separate adapter tests.

Changing embeddings may require a new index; changing a transcription model
must not relabel historical transcripts as if the new model produced them.
See [installation](INSTALL.md), [release readiness](RELEASE_READINESS.md) and
the [contribution guide](../CONTRIBUTING.md).
