"""Prompt templates, verbatim from the report's Section 5.7."""

SYSTEM_SYNTHESIS = """\
You are a research assistant that answers ONLY from the provided sources.
Rules:
- Every factual claim MUST cite at least one source by its [id].
- If the sources do not answer the question, say so plainly. Do not guess.
- Do not use prior knowledge to add facts not present in the sources.
- Prefer primary/official sources; if sources conflict, surface the conflict.
- Be concise. Distinguish what is stated from what is inferred."""

DECOMPOSITION_PROMPT = """\
Break the user's question into the minimal set of sub-questions needed to
answer it. For each sub-question, tag whether it is best answered by
[text] retrieval or [graph] relationship lookup. Return JSON only:
{ "subquestions": [ { "q": "...", "route": "text|graph" } ] }"""


def build_synthesis_user_message(question: str, sources: list[dict]) -> str:
    lines = [f"Question: {question}", "", "Sources:"]
    for src in sources:
        label = src.get("label", "")
        lines.append(f"[{src['id']}] ({label}) {src['text']}")
    lines.append("")
    lines.append("Write the answer following the system rules. Cite every claim by [id].")
    return "\n".join(lines)
