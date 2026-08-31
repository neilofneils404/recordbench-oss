# OCR and media

Uploads are streamed into a private staging boundary and scanned before they
become matter sources. RecordBench extracts PDF and DOCX structure, email and
spreadsheet text, and bounded image content. PDF pages without usable text are
rendered with Poppler and recognized with Tesseract. OCR page, pixel, byte, and
time limits protect the shared node; failures remain visible per source and do
not block searching the rest of a matter.

Audio and video are playable even when transcription fails. Browser-incompatible
video is prepared asynchronously with FFmpeg, using remux or audio-only
conversion before full re-encoding when possible. Playback follows the active
transcript, and cited media timestamps can seek directly to the relevant span.

The bundled transcription queue reports submission, queue, transcription,
alignment, diarization, projection, summary, completion, degraded, and failed
states. RecordBench indexes timestamped segments and automatically generates a
source summary after projection. Users can export transcripts, summaries,
clips, citations, and reports.

Keep the transient transcription root out of backup and indexing systems. The
matter-owned original and projected transcript remain governed by the matter’s
own lifecycle; the standalone worker queue is deleted after delivery/expiry.
