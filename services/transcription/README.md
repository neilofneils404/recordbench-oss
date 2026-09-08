# RecordBench Transcription Service

This bundled service provides RecordBench's durable media queue, WhisperX
transcription, forced alignment, optional Community-1 speaker diarization,
review exports, and short-lived delivery lifecycle. It can also run the
optional Transcript Studio UI.

The API, worker, and cleanup path are bundled into the private Compose mesh.
Transcript Studio is not published by the default deployment; an operator who
enables it must place it behind the same trusted authentication boundary.

Real inference is deliberately offline. Model terms are accepted and pinned
artifacts are staged with the root installer before the worker starts. The
Hugging Face token is never placed in the runtime environment.

See the root installation guide and [model policy](../../docs/MODELS.md).

For the experimental Apple Silicon CPU worker, see
[CPU execution and validation](docs/CPU_EXECUTION.md).
