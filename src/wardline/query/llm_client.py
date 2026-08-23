"""LLM client abstraction for the query/agent planes.

`settings.llm_client_mode` selects the implementation: "mock" (default in
this environment — no LLM_API_KEY is configured) or "live" (real calls to
`settings.llm_provider`'s API). Both implement the same Protocol so
query/pipeline.py and agent/loop.py never know which one they're talking to.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.query.prompts import (
    DECOMPOSITION_PROMPT,
    SYSTEM_SYNTHESIS,
    build_synthesis_user_message,
)

logger = get_logger(__name__)


class SubQuestion:
    def __init__(self, q: str, route: str):
        self.q = q
        self.route = route


class LLMClient(Protocol):
    def decompose(self, question: str) -> list[SubQuestion]: ...
    def synthesize(self, question: str, sources: list[dict]) -> str: ...
    def next_action(self, question: str, history: list[dict]) -> dict:
        """Agent loop (report 5.8): given the question and prior
        {tool, args, result} steps, return the next {"tool": ..., "args": ...}
        to take. Tool set: search_text | graph_lookup | resolve_entity | finish."""


# Relationship-style keywords route to "both" (text + graph) even in mock mode,
# so Phase 5's graph_lookup gets exercised without needing a live LLM.
_RELATIONSHIP_HINTS = re.compile(
    r"\b(founders?|founded|co-?founded?|subsidiary|acquir|owns?|parent company|relationship|related to)\b",
    re.IGNORECASE,
)


class MockLLMClient:
    """Deterministic, no-network synthesizer used when LLM_CLIENT_MODE=mock.

    Not a stub that returns a canned string — it does real extractive work
    over whatever sources retrieval actually found, so the query pipeline's
    plumbing (citation verification, audit logging, response shaping) is
    exercised meaningfully without requiring a real API key.
    """

    def decompose(self, question: str) -> list[SubQuestion]:
        route = "both" if _RELATIONSHIP_HINTS.search(question) else "text"
        return [SubQuestion(q=question, route=route)]

    def synthesize(self, question: str, sources: list[dict]) -> str:
        if not sources:
            return "The provided sources do not answer this question."
        sentences = []
        for src in sources[:5]:
            snippet = src["text"].strip().replace("\n", " ")
            snippet = snippet[:220].rsplit(" ", 1)[0] if len(snippet) > 220 else snippet
            snippet = snippet.rstrip(".")
            # The citation bracket must sit *before* the sentence-ending period:
            # verify.py splits sentences on `[.!?]\s+`, so "snippet. [id]" puts the
            # split between "." and "[", shifting every citation onto the next
            # sentence. "snippet [id]." keeps the id inside its own sentence.
            sentences.append(f"{snippet} [{src['id']}].")
        return " ".join(sentences)

    def next_action(self, question: str, history: list[dict]) -> dict:
        # A real, if scripted, multi-step trajectory: search text first, then
        # check the graph, then finish citing whatever was actually gathered —
        # not a canned string, so the loop's budget/dedup/citation-enforcement
        # logic gets genuinely exercised.
        if len(history) == 0:
            return {"tool": "search_text", "args": {"query": question, "k": 8}}
        if len(history) == 1:
            return {"tool": "graph_lookup", "args": {"entity": question, "hops": 1}}

        gathered: list[dict] = []
        for step in history:
            result = step.get("result")
            items = result if isinstance(result, list) else [result]
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    gathered.append(item)

        if not gathered:
            return {"tool": "finish", "args": {"answer": "", "citations": []}}
        answer = self.synthesize(question, gathered[:5])
        return {"tool": "finish", "args": {"answer": answer, "citations": [g["id"] for g in gathered[:5]]}}


class AnthropicLLMClient:
    """Live LLM client, Anthropic backend. Requires LLM_API_KEY
    (LLM_CLIENT_MODE=live, LLM_PROVIDER=anthropic — the default and, for
    now, only implemented provider)."""

    def __init__(self):
        import anthropic

        settings = get_settings()
        self._model = settings.llm_model
        self._client = anthropic.Anthropic(api_key=settings.llm_api_key)

    def decompose(self, question: str) -> list[SubQuestion]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=DECOMPOSITION_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        try:
            payload = json.loads(_strip_code_fence(text))
            return [SubQuestion(q=sq["q"], route=sq["route"]) for sq in payload["subquestions"]]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("llm.decompose_parse_failed", error=str(exc), raw=text[:500])
            return [SubQuestion(q=question, route="text")]

    def synthesize(self, question: str, sources: list[dict]) -> str:
        user_message = build_synthesis_user_message(question, sources)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_SYNTHESIS,
            messages=[{"role": "user", "content": user_message}],
        )
        if response.stop_reason == "refusal":
            logger.error("llm.synthesis_refused")
            return "The model declined to answer this question."
        return next((b.text for b in response.content if b.type == "text"), "")

    def next_action(self, question: str, history: list[dict]) -> dict:
        from wardline.agent.prompts import AGENT_SYSTEM_PROMPT, build_agent_user_message

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_agent_user_message(question, history)}],
        )
        if response.stop_reason == "refusal":
            return {"tool": "finish", "args": {"answer": "The model declined to answer.", "citations": []}}
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        try:
            return json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as exc:
            logger.error("llm.next_action_parse_failed", error=str(exc), raw=text[:500])
            return {"tool": "finish", "args": {"answer": "", "citations": []}}


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"```$", "", stripped.strip())
    return stripped


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_client_mode != "live":
        return MockLLMClient()
    if settings.llm_provider == "anthropic":
        return AnthropicLLMClient()
    raise ValueError(f"unsupported LLM_PROVIDER: {settings.llm_provider!r}")
