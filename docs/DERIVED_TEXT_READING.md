# Bounded derived-text reading

`PilotDocument.iter_parsed_units()` reads the existing version-1 derived-unit
JSON container one record at a time. This does not change stored data or the
materializing `parsed_units()` API used by existing callers.

Budgeted consumers can supply `budget_check()` before and after each 64-KiB
character read, after each framing pass, and before and after JSON decoding;
`read_check(count)` to charge aggregate serialized characters; and
`max_record_chars` to cap a complete or unfinished record **before** decoding.
Callbacks propagate their own exceptions. A record is framed incrementally and
decoded once, without repeatedly decoding its growing prefix. The default
record cap preserves a 10-million-character unit even with surrogate-pair JSON
escaping. Consumers should set a smaller cap when their own allowance requires
it, and charge decoded text and unit counts before retaining each yielded unit.

Budgeted file-backed documents require the streaming reader bound by
`PilotStore`; they fail closed if only a legacy whole-file loader is available.
Unbudgeted callers retain the legacy fallback. Inline units receive the same
per-unit deadline checks. A file-backed document with neither reader bound is
unavailable for every iterator caller; it cannot be classified as empty without reading
its derived text. Malformed containers, versions, trailing content,
excessive nesting and oversized records remain explicit failures.

These are cooperative limits: one bounded file read or JSON decode cannot be
preempted. Callers retain their authorization and source-mutation locks and
must suppress partial output if any limit or source read fails. Synthetic tests
cover file-backed reads, slow-read deadlines, serialized input charging,
oversized and unfinished first records before decoding, Unicode escapes,
container validation and the legacy-loader boundary.
