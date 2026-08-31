# Local model portfolio

The review pipeline uses one pinned generator tier plus the same retrieval
stack:

- portable: Qwen3.5 4B for constrained or shared-GPU nodes;
- quality: Qwen3.5 9B when the selected generator device has sufficient VRAM;
- Granite Embedding English R2 for dense retrieval;
- GTE ModernBERT cross-encoder for reranking;
- deterministic source-support verification after generation.

Automatic selection considers visible GPU memory and whether transcription
shares the generator device. Operators may select a tier and GPU layout
explicitly, including tensor-parallel generator devices, but preflight rejects
known-unworkable combinations. The defaults are deployment candidates, not a
universal quality claim.

GPU count is not an edition boundary. The same workflows run on a supported
one-GPU node or a larger node; extra devices change placement and potential
throughput, not product behavior. Automatic placement uses at most three
service lanes. Deliberately spreading generation across more devices or adding
replicas requires acceptance on that exact topology.

Larger collection questions still use retrieval rather than placing thousands
of documents in one prompt. Collection-wide counts, exhaustive chronologies,
and document-by-document classification use dedicated research/full-review
workflows that preserve progress and per-source decisions.

The transcription profile is modular: faster-whisper/WhisperX `large-v3` ASR,
English alignment, Spanish alignment, translation through the staged ASR
artifact, and Community-1 diarization are separately described and selected.
Only diarization is gated by default. Community-1 produces anonymous speaker
clusters, not identity. Transcripts describe what the machine heard and are not
automatically treated as facts.

Every model entry must retain model ID, exact immutable revision, license,
source, hashes/manifest, evaluation evidence, and GPU/runtime envelope. Gated
tokens are staging-only. Confidential runtime is offline and telemetry-free.
