"""The bounded agentic research loop (report 5.8): the model proposes the
next retrieval action, the controller executes it, results return, repeat
until the question is covered or a step/token budget is hit. Every tool
call is logged to the audit trail; `finish` requires citations.
"""

from __future__ import annotations

import hashlib
import time

from sqlalchemy.orm import Session

from wardline.agent import tools
from wardline.agent.guardrails import AgentBudget, estimate_tokens
from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.governance import audit, pep
from wardline.query.llm_client import get_llm_client
from wardline.query.render import watermark
from wardline.query.verify import verify_citations
from wardline.storage.models.governance import User

logger = get_logger(__name__)

_DISPATCH = {"search_text", "graph_lookup", "resolve_entity"}


def run_agent(
    db: Session,
    *,
    user: User,
    question: str,
    filters: dict | None = None,
    max_sources: int = 12,
) -> dict:
    settings = get_settings()
    filters = filters or {}
    start = time.monotonic()

    session_id = audit.open_session(db, user.id, question, "research")
    llm = get_llm_client()
    budget = AgentBudget(max_steps=settings.agent_max_steps, max_total_tokens=settings.agent_max_total_tokens)

    history: list[dict] = []
    gathered: dict[str, dict] = {}
    final_answer = ""
    final_citations: list[str] = []
    stop_reason = "max_steps_exhausted"

    while not budget.steps_exhausted() and not budget.tokens_exhausted():
        action = llm.next_action(question, history)
        tool = action.get("tool")
        args = action.get("args", {}) or {}
        tokens = estimate_tokens(str(action))
        budget.record_step(tokens)

        audit.log_event(db, session_id, "tool_call", user.id, {"tool": tool, "args": args})

        if tool == "finish":
            final_answer = args.get("answer", "") or ""
            final_citations = args.get("citations", []) or []
            stop_reason = "finished"
            break

        if tool not in _DISPATCH:
            history.append({"tool": tool, "args": args, "result": {"error": "unknown tool"}})
            continue

        if budget.is_duplicate_call(tool, args):
            history.append({"tool": tool, "args": args, "result": {"error": "duplicate call skipped"}})
            continue

        if tool == "search_text":
            result = tools.search_text(db, args.get("query", question), k=args.get("k", 10), filters=filters)
        elif tool == "graph_lookup":
            result = tools.graph_lookup(db, args.get("entity", question), args.get("relation"), args.get("hops", 1))
        else:
            result = tools.resolve_entity(db, args.get("name", question), args.get("context", ""))

        for item in result:
            gathered[item["id"]] = item

        history.append({"tool": tool, "args": args, "result": result})

    # Guardrail: finish must cite something real; a claim without a citation
    # is dropped rather than trusted (mirrors query/verify.py's rule). The
    # model's answer text is expected to carry its own inline [id] markers —
    # verify_citations checks those directly against what was actually
    # retrieved, same as the non-agentic pipeline.
    valid_ids = set(gathered.keys())
    verified = (
        verify_citations(final_answer, valid_ids)
        if final_answer and final_citations
        else verify_citations("", valid_ids)
    )

    final_text = watermark(session_id, verified.text) if verified.text else ""
    latency_ms = int((time.monotonic() - start) * 1000)
    answer_hash = hashlib.sha256(final_text.encode("utf-8")).hexdigest()

    sources_payload = [
        {"id": item["id"], "text": item["text"], "kind": "edge" if item["id"].startswith("edge_") else "chunk"}
        for item in gathered.values()
    ]
    sources_payload = pep.filter_sources_by_license(user, sources_payload)
    cited_ids = sorted({sid for claim in verified.claims for sid in claim.supported_by})
    used_sources = [s for s in sources_payload if s["id"] in cited_ids]

    audit.log_event(
        db, session_id, "agent_stopped", user.id, {"reason": stop_reason, "steps_used": budget.steps_used}
    )
    audit.close_session(
        db,
        session_id,
        user.id,
        retrieved=list(gathered.keys()),
        latency_ms=latency_ms,
        answer_hash=answer_hash,
        token_cost=budget.tokens_used,
    )

    return {
        "session_id": session_id,
        "answer": final_text if not verified.insufficient_evidence else "The agent found insufficient evidence to answer this question.",
        "claims": [{"id": c.id, "text": c.text, "supported_by": c.supported_by} for c in verified.claims],
        "sources": [{"id": s["id"], "doc_id": None, "uri": None, "title": None, "license": None, "kind": s["kind"]} for s in used_sources],
        "confidence": verified.confidence,
        "insufficient_evidence": verified.insufficient_evidence,
        "latency_ms": latency_ms,
    }
