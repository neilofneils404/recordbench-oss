# Investigation budgets and accounting

Investigations use an explicit, capability-neutral `ReviewBudget` policy shared
by orchestration, retrieval validation, generation bounds, saved progress, and
exports. This policy represents the supported application contract; it does not
inspect the development computer, select limits by operating system, or assume a
particular GPU. Retrieval and per-generation packet limits remain unchanged. Explicit continuation
can extend the search budget as described below.

The default policy permits five search passes and 900 search-step seconds,
20 primary candidates per pass,
12 supplemental candidates per missing requested source kind, 12 selected
passages per pass, 72 unique ledger passages, and 12 original synthesis inputs per generation.
New investigations use the separate [hierarchical synthesis](HIERARCHICAL_SYNTHESIS.md)
receipt for issue groups, matter sections, charged requests and a first-start deadline.
Each generation receives at most 6,000 characters per passage and 48,000 evidence
characters total, with a 1,200 output-token request. Packets now obey both text
limits and record the number of omitted characters. A request for 30 primary
results is rejected before retrieval; investigations request the supported 20.

Requested and effective limits are saved separately and are equal for current
runs. Fewer matches are actual results, not an undisclosed reduction in budget.
Candidate occurrences count repeated returned passages. Adaptive investigations
exclude already selected passages before selecting new generation inputs. Unique selected passages and candidate sources are deduplicated.
Candidate sources means sources represented in returned results, not every source
in the searched index. Unavailable-source counts describe matter availability at
run start; the existing completion coverage notice separately describes changes
while the run executes. A source-set run can therefore have unavailable matter
sources outside its selected scope. These counts never imply a pages-read
percentage, an exhaustive source review, or that selected text produced a verified
finding. Analyzed units are generation inputs, including rejected findings.

The evidence ledger retains exact original locators and excerpts. Truncation
counts refer to text omitted from each generation packet, including repeated
occurrences and legacy final synthesis; source text is not changed. Hierarchical
synthesis separately reports original characters outside its bounded packets.
Its synthesis-input count covers distinct originals admitted to completed issue
groups, and can be lower than the selected ledger. Charged interrupted requests
remain in the separate synthesis receipt. Progress counts cover committed pass checkpoints; cancellation can leave
an in-flight generation uncounted. Legacy completion records `completed_bounded_plan`; adaptive runs record
`pass_budget`, `time_budget`, `evidence_budget`, `no_new_evidence`, or
`queue_exhausted`;
cancellation and failure record distinct terminal reasons in result JSON.

The existing JSON columns contain a version-2 `budget` object with `requested`,
`effective`, `counts`, and `stop_reason`, plus a top-level terminal `stop_reason`.
No database schema migration is needed. Version-1 budgets remain readable and
explicitly show that search-time limits were not recorded. Older saved runs retain unknown metadata;
we do not infer historical counts from old coverage fields. Active checkpoints
without budget accounting restart retrieval, preserving exact-source validation.
Current checkpoints survive restart and clean SQLite backup/restore. The details
page, status response, and JSON/Markdown/Word exports use the same allowlisted
metadata and description; arbitrary saved metadata is not exported.

## Capacity evolution

The policy is a shared seam for future server capability negotiation. Higher
capacity should arrive as a validated backend policy applied consistently to
retrieval, orchestration, generation context, scheduling, and checkpoint recovery.
Hierarchical synthesis records each stage's input/output budget and carries
original support through intermediate summaries. Its bounded sections do not
establish exhaustive coverage. Increasing one retrieval argument
alone is not a capacity upgrade. Resource-admission and evidence-quality tests
must accompany a higher-capacity policy, independently of the developer's host.

## Synthetic validation

`tests/test_investigation_budget.py` covers 30 requested results from 50 matches,
fewer available matches, repeated passages, packet character bounds, UI/status/
export agreement, cancellation, recovery, compatibility, portable metadata, and
SQLite online backup followed by clean restore and integrity checking. Existing
research, generation, export, and changing-source coverage tests remain applicable.
These local tests do not validate a Linux/GPU deployment or model throughput.

See [evidence-driven investigation](EVIDENCE_DRIVEN_INVESTIGATION.md) for the
source-backed queue, checkpoint resumption, and explicit additional budgets.
