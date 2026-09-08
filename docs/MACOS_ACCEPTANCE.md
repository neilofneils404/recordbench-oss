# Apple Silicon acceptance record — 2026-09-08

Status: **standalone runtime demonstrated; experimental, not production qualified**.
All inputs were generated or existing synthetic repository fixtures. No remote
RecordBench deployment or confidential material was used.

The runtime results below describe the initial compatibility prototype, before
integration onto the latest upstream application. Contribution checks are
recorded separately; these results do not qualify every newer product workflow.

## Observed environment

- Apple M4 with 32 GiB unified memory.
- Colima 0.10.3, ARM64 Linux, four virtual CPUs and 12 GiB VM memory.
- Native Ollama 0.33.3 on Metal, dedicated loopback listener and model vault.
- CPU retrieval with the existing pinned Granite embedding and GTE reranker.
- WhisperX 3.8.6, existing pinned large-v3 ASR and English alignment, CPU int8,
  batch size one, 6 GiB worker memory limit, and runtime networking disabled.
- Loopback HTTPS with a locally generated certificate and local account auth.

## Demonstrated behavior

| Check | Result |
| --- | --- |
| Core Linux ARM64 suite | 695 passed; 12 optional tests skipped; 2 installer tests checked separately on the Mac |
| Bundled transcription suite | 201 passed |
| Final focused Mac/model/startup/readiness checks | 51 passed |
| Publication scan of current files | Clean |
| Secure login and matter creation | Passed through the running HTTPS app |
| Text, PDF, DOCX, image OCR, and audio intake | Five of five sources searchable, none excluded |
| Local retrieval and cited answer | Expected location and time returned from the synthetic source |
| Word conversation export | Valid DOCX downloaded |
| Restart persistence | Existing matter, sources, account, and answer retained after VM restart |
| Offline transcription and exports | Actual model inference, word alignment, exports, provenance, and scratch deletion passed |
| Browser rendering after login | Corrected external-origin asset URLs; layout verified in Chrome |
| Final service readiness | All nine selected services ready; native model digest matched |

The 12 optional core skips comprise eight isolated PostgreSQL tests and four
Compose-CLI tests unavailable inside the test container. The real Mac Compose
graph and installer were checked separately. The isolated Linux test environment
used a 1 GiB free-space reserve; the installed Mac application retains its 15 GiB
reserve. Do not interpret the test override as a production configuration.

The immutable CPU transcription image processed a 6.335-second generated English
recording in 21.029 seconds, with zero normalized word errors, three segments,
and 16 aligned words. Export formats, ZIP integrity, approved-model provenance,
and deletion were checked. This is one short fixture, not an accuracy or
throughput benchmark. See [CPU execution evidence](../services/transcription/docs/CPU_EXECUTION.md).

## Open qualification gates

- Native Qwen3.5 4B passed 6/10 frozen answer-quality cases; 9B passed 5/10.
  Both remain evaluation candidates. The 4B model remains the default.
- A separate 16K-context capacity probe passed with 14,181 prompt tokens and
  citations to facts at both ends. The Mac launcher selects 16K context and a
  300-second timeout. This does not establish full long-conversation quality.
- Speaker diarization is not staged. The app preserves the explicit degraded
  speaker-separation notice while retaining searchable timestamps/transcripts.
- The transcript worker requires substantial memory: 4 GiB OOM-killed; 5 GiB
  completed but reached its cap. The selected 6 GiB limit also reached its cgroup
  cap during the successful run. Longer recordings and concurrent load still
  require capacity evaluation.
- Clean backup/restore, upgrade automation, long collections, sleep/wake,
  broader browser workflows, and independent clean-Mac installation remain open.
  Basic authenticated page rendering was verified in an existing browser session.

See [standalone setup](MACOS.md) and [model evidence](MAC_MODELS.md) for commands,
model digests, security boundaries, and the distinction between runtime readiness
and answer-quality acceptance.

Static assets use origin-relative URLs so the browser preserves HTTPS and the
configured external port, even when the internal proxy request uses HTTP.
A synthetic template regression covers the workbench, workspace, and source view.

## Contribution checks on current upstream

The contribution was integrated onto upstream `26f5ece` without bringing the
prototype checkout's older local history. The integrated candidate passed the
application suite in an isolated ARM64 Linux container (1,104 passed,
14 skipped), 203 bundled
transcription tests, native Mac installer/model checks, Python compilation,
and standard/Kerberos Compose validation. The application test environment
installed the candidate's own declared dependencies, including speech preflight.
The tree and its intended outgoing ancestry passed publication inspection.
The test-only storage reserve was 1 GiB; the installed profile remains 15 GiB.
These checks do not imply an upgrade or requalification of the running prototype.

Five skipped Mac Compose checks passed separately on the host. Eight optional
PostgreSQL integration checks and one encrypted backup integration check were
not run in this contribution gate.
