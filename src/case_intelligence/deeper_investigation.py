"""Optional explicit widening of a model's saved not-answerable response."""
from __future__ import annotations

import os
import uuid


def install_deeper_investigation(templates, *, bench, auth_context):
    """Add a read-only template helper; submission uses the existing Ask route."""
    enabled = os.getenv("CASE_INTELLIGENCE_DEEPER_INVESTIGATION", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }

    def offer(request, matter, message):
        if (not enabled or message.role != "assistant" or message.payload.get("answerable") is not False
                or message.payload.get("generator_answerable") is not False
                or message.payload.get("model_called") is not True
                or message.payload.get("kind") != "not-supported" or message.payload.get("workflow") == "research"):
            return None
        actor = auth_context(request).principal_id
        with bench.workspace._lock:
            try:
                bench.workspace.membership(matter.matter_id, actor)
                bench.workspace.get_conversation(matter.matter_id, message.conversation_id)
            except KeyError:
                return None
            # A preceding message need not be this answer's question when jobs
            # complete out of order. Use the durable job/result/question binding.
            row = bench.workspace.connection.execute(
                "SELECT j.question,s.source_set_id FROM workbench_answer_job j "
                "JOIN workbench_message q ON q.message_id=j.question_message_id "
                "AND q.conversation_id=j.conversation_id AND q.role='user' AND q.content=j.question "
                "LEFT JOIN workbench_answer_source_scope s ON s.job_id=j.job_id AND s.matter_id=j.matter_id "
                "WHERE j.matter_id=? AND j.conversation_id=? AND j.result_message_id=? AND j.state='succeeded'",
                (matter.matter_id, message.conversation_id, message.message_id),
            ).fetchone()
            if row is None or not row["question"] or len(row["question"]) > 2_000:
                return None
            scope = row["source_set_id"] or ""
            if message.payload.get("source_scope") and not scope:
                return None
            scope_available = True
            if scope:
                try:
                    scope_available = bench.workspace.source_set(matter.matter_id, scope).source_count > 0
                except KeyError:
                    scope_available = False
            active = bench.workspace.connection.execute(
                "SELECT 1 FROM workbench_answer_job WHERE matter_id=? AND conversation_id=? AND state IN ('queued','running') "
                "UNION ALL SELECT 1 FROM workbench_research_job WHERE matter_id=? AND conversation_id=? AND state IN ('queued','running') LIMIT 1",
                (matter.matter_id, message.conversation_id, matter.matter_id, message.conversation_id),
            ).fetchone()
            ready = bench.workspace.matter_readiness(matter.matter_id).can_query
        disabled = not scope_available or not ready or not bench.generator.available or active is not None
        reason = ("The original source scope is unavailable." if not scope_available else
                  "Wait for the current review work to finish." if active is not None else
                  "Source preparation and local answering must be ready." if disabled else "")
        key = uuid.uuid5(uuid.NAMESPACE_URL, f"recordbench:deeper:{matter.matter_id}:{message.message_id}:{actor}").hex
        return dict(question=row["question"], conversation=message.conversation_id, source_set=scope,
            request_key="answer-request-" + key, disabled=disabled, reason=reason,
            has_context=bool(message.payload.get("recorded_context_job") or message.payload.get("notebook_context")))

    templates.env.globals.update(deeper_investigation_enabled=enabled, deeper_investigation_offer=offer)
