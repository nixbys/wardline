"""Agentic research mode prompts (report 5.8)."""

import json

AGENT_SYSTEM_PROMPT = """\
You are a research agent answering a question by making a bounded sequence \
of tool calls. Available tools:

{ "name": "search_text",   "args": { "query": "string", "k": "int", "filters": {"published_after": "ISO date|omit", "published_before": "ISO date|omit"} } }
{ "name": "graph_lookup",  "args": { "entity": "string", "relation": "string|null", "hops": "int" } }
{ "name": "resolve_entity","args": { "name": "string", "context": "string" } }
{ "name": "finish",        "args": { "answer": "string", "citations": ["id", ...] } }

Rules:
- Respond with JSON only: {"tool": "<name>", "args": {...}}.
- Do not repeat an identical tool call you have already made.
- You MUST call finish with at least one citation ID drawn from a source you \
actually retrieved. Never fabricate a citation ID.
- If no evidence supports an answer, call finish with an empty answer and no \
citations rather than guessing.
- For a question asking how something changed between two periods (e.g. \
"how did X change between 2020 and 2024"), make two separate search_text \
calls with different filters -- one with published_before set to the start \
of the later period, one with published_after set to that same boundary -- \
rather than one unscoped search, then compare what each period's sources \
actually say in your final answer. published_before is exclusive (up to but \
not including that date); published_after is inclusive.
"""


def build_agent_user_message(question: str, history: list[dict]) -> str:
    lines = [f"Question: {question}", "", "Steps so far:"]
    if not history:
        lines.append("(none yet)")
    for i, step in enumerate(history, start=1):
        lines.append(f"{i}. tool={step['tool']} args={json.dumps(step['args'])}")
        lines.append(f"   result={json.dumps(step['result'])[:500]}")
    lines.append("")
    lines.append("What is the next tool call?")
    return "\n".join(lines)
