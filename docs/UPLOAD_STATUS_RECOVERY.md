# Upload status recovery

Status: implemented and locally validated for issue #31; final-head hosted
reviews and the normal merge gate remain required.
No runtime activation is implied.

## Staff outcome

Polling or reloading an upload while a chunk arrives preserves the newest saved
byte count. Finalized collections remain complete, and cancelled collections
remain cancelled. A status check cannot change either to partial because it
observed older progress. The same receipt and exact source identity survive
ordinary resumption and finalization.

Genuinely missing staged bytes still produce the existing incomplete-upload
message and retained receipt. Select the source in a new upload collection to
recover. An unresolved checkpoint conflict returns an understandable retry
message without claiming that unsaved bytes were received.

## Implementation

Full status reconciliation acquires the existing matter source-store lock before
reading control checkpoints, using the same source-then-control lock order as
chunk writes. It verifies staged byte sizes and reconciles only active items,
then returns the current authorized session/item snapshot. Compare-and-set
updates remain mandatory. If cancellation records a terminal state before
acquiring the source lock for byte cleanup, reconciliation accepts the changed
current state rather than propagating a stale offset error. An unchanged state
with an unresolved error is returned as HTTP 409, not a successful status.

Failure recording does not update the parent collection when its item update
cannot affect an already queued or cancelled item. This keeps terminal collection
state stable even when cancellation overlaps missing-byte detection. The lock
is local to the existing matter source store; unrelated matters do not acquire
it. Compact status behavior, file bounds, original preservation, malware checks,
source versions, receipt accounting and finalization admission remain unchanged.

## Evidence and recovery

The first generated HTTP run reproduces four failures: an advancing chunk and
cancellation during checkpoint recovery return server errors, while concurrent
finalization and cancellation can turn terminal collections partial. Eight
regressions cover those interleavings, cancellation while detecting missing
bytes, genuine missing-byte recovery, foreign-matter denial and an unresolved
checkpoint conflict. Successful recovery verifies exact source bytes, one source
occurrence, its receipt/version binding and portable receipt output.

Run the focused selection and actual browser workflow:

```console
python -m pytest -q tests/test_upload_status_reconciliation.py tests/test_intake_receipt_limit_http.py tests/test_upload_occurrences.py
python scripts/browser-accept-intake-receipts.py --chrome-binary /path/to/chrome --chromedriver /path/to/chromedriver --output /tmp/generated-upload-recovery
make check
```

The browser uses generated nested selection, lost-response/storage-denied retry,
interrupted seven-byte resumption, cancellation, capacity cleanup, exact support
opening and exports. Its cleanup wait reads the current document atomically so
a navigation between element lookup and text read cannot fail the harness.

No schema, dependency, registry or export-format change is included. Code rollback
retains all stored uploads and receipts but restores the earlier polling race;
prefer a forward correction after use. Never roll stored progress back merely
to undo source code. `make check` passes 1067 application tests with nine optional skips, all 194
transcription tests, compilation, both Compose graphs and publication inspection.
The focused selection passes 33 tests. All 11 intake browser workflows pass with
no application errors, retaining external originals and exact receipt/source
support. Final-head hosted review and CI evidence are required before merge.
