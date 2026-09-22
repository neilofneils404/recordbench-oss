# Continuity C — recorded selected context in focused answers

**Done — September 22, 2026.** PR #107 landed at
`3c814e37adf18a84de9191bad84e0e8a2745e525` after full Quality, requested hosted code
review and fixed-corpus real-model acceptance. The
[landing receipt](../EXIT_ALPHA_CRUISE.md#continuity-c-landing-receipt) supersedes
pre-landing status notes. See the
[dated acceptance/handoff record](../CONTINUITY_C_ACCEPTANCE_2026-09-22.md).
Implementation base: `dcee0cfb7912a4289faef5e8646fc33b82da128a`.
B implementation PR #103 landed at `d21c1d4849b46b8ae85db19b4d2ce80c8a9669a8`;
its accepted landing receipt is `2a50ae6be36182d73c1d76d7896f68096bc18c29`.
The planning baseline was `0d59d5fe4f7be575a66039274415de945a6d5db5`.
Changes since then are B, the Report test lease correction, and Quality's
documentation-only path. Preserve them and the original checkout's unrelated
onboarding edits. This clean worktree selects no held product areas.

An unchecked option in the focused composer freezes the requesting reviewer's
complete approved selection in the existing `/matters/{slug}/ask` transaction.
Conflicting legacy confirmed/selected modes are refused. Off means no optional
packet; previous chat history and ordinary retrieval remain independent.
No investigations, full-text review, synthesis or Report compilation consume it.

Paired migration 0036 retains immutable submission JSON and immutable prepared
request manifests. Request-key retries recover the accepted snapshot. Later
selection/record edits affect future requests. Original invalidation, active
membership/conversation, cancellation and worker attempts fence dispatch and save.
No write transaction extends through model inference. Failed/cancelled/prepared
attempts remain inspectable and included in complete matter exports.

Orientation keeps typed IDs, uncertain dates, human status and attribution.
It is never evidence. Complete direct original groups are independently verified,
matter/source-set/kind restricted, deduplicated by complete original identity,
and admitted within existing evidence ceilings. No graph walk or retrieval
rewrite. Required support plus competition fits together or the question fails
with explicit repair/removal/scope recovery. No silent selected-record clipping.

The new path requires the configured vLLM-compatible `/tokenize` chat endpoint:
identical messages and chat-template kwargs, runtime token IDs/count and actual
`max_model_len`. Complete input plus 1,200 reserved output tokens and a 256-token
margin must fit. Existing character/count ceilings also apply. Other adapters
and unavailable/malformed runtime capacity fail closed for this option. This
changes no model, downloads no weights and raises no limit. The tokenizer request
itself sends input to the same configured runtime before inference; it is part
of preparation. The runtime must retain ordinary oversize rejection, with prompt
truncation disabled. [vLLM's tokenization contract](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/serve/tokenize/protocol/)
and [input validation](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/openai/engine/serving/)
document these endpoint semantics. The dated follow-up records live
configured-profile validation; deterministic transport tests alone do not
establish model usefulness.
Both endpoints explicitly use `add_generation_prompt=true` and
`add_special_tokens=false`, matching the documented
[chat completion defaults](https://docs.vllm.ai/en/v0.15.1/api/vllm/entrypoints/openai/chat_completion/protocol/)
without depending on differences between adapter defaults.

“Context supplied” describes application dispatch, not model attention or
immutable per-response model attestation. Exact request JSON, wire digest, budget,
normalization, evidence admission/routes/omissions and repair differences are
retained. Prepared, dispatch attempted, transport failed and completed are separate.
A timeout cannot establish that the model never received the request. Available
model/runtime identifiers must be qualified; configured names are not attestations.

Answer/conversation exports carry the context receipt; complete exports also
retain unfinished attempts. Note-only export remains note-only. Report copy of
these answers is refused with an explanation until it can preserve the notice.
Context labels are never Report citations. All new state shares control-database
backup, clean restore and matter purge. Stop writers before upgrading; rollback
requires the verified pre-upgrade complete backup and its matching reader.
Mixed-version writers are unsupported. General logs contain no case text.

Acceptance requires synthetic service, HTTP, concurrency, browser and restore
coverage, current Quality/publication gates, and a small real configured-model
new-conversation corpus with identity separation, disagreement and unsupported
claim checks. Runtime unavailability leaves that last gate outstanding rather
than substituting mocks or another model. The initial implementation task did
not authorize publication or deployment; subsequent maintainer authorization
and the repository publication/review gates govern landing.

Implementation refinement: tokenizer requests are also recorded before transport,
so an oversize request still exposes what preparation sent. Sixteen runtime
requests per job bound retries/repairs; this is not sixteen inference calls.
The normal chat response must report the same input-token count as admission;
a mismatch retains the completed dispatch but refuses answer acceptance. C adds
an exact-original-span gate after the existing verifier, including limitations,
to prevent overlap scoring from importing context-only nouns into facts. Useful
paraphrase capacity is deliberately constrained. Live acceptance caught shortened
identity wording; explicit intact-sentence instructions now preserve the original
description while keeping the verifier unchanged. The dated receipt limits the
passing result to its fixed synthetic corpus.
