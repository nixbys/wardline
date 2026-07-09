"""LLM client abstraction for the query/agent planes.

`settings.llm_client_mode` selects the implementation: "mock" (default in
this environment — no ANTHROPIC_API_KEY is configured) or "live" (real
Anthropic API calls). Both implement the same Protocol so query/pipeline.py
and agent/loop.py never know which one they're talking to.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from cranus.common.config import get_settings
from cranus.common.logging import get_logger
from cranus.query.prompts import DECOMPOSITION_PROMPT, SYSTEM_SYNTHESIS, build_synthesis_user_message

logger = get_logger(__name__)


class SubQuestion:
    def __init__(self, q: str, route: str):
        self.q = q
        self.route = route


class LLMClient(Protocol):
    def decompose(self, question: str) -> list[SubQuestion]: ...
    def synthesize(self, question: str, sources: list[dict]) -> str: ...
    def chat(self, system: str, messages: list[dict]) -> str:
        """Single-turn-or-more raw chat call, used by the agent loop."""


# Relationship-style keywords route to "both" (text + graph) even in mock mode,
# so Phase 5's graph_lookup gets exercised without needing a live LLM.
_RELATIONSHIP_HINTS = re.compile(
    r"\b(founder?|co-?founded?|subsidiary|acquir|owns?|parent company|relationship|related to)\b",
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
            sentences.append(f"{snippet}. [{src['id']}]")
        return " ".join(sentences)

    def chat(self, system: str, messages: list[dict]) -> str:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return f'{{"tool": "finish", "args": {{"answer": "mock response to: {last_user[:80]}", "citations": []}}}}'


class AnthropicLLMClient:
    """Live Claude client. Requires ANTHROPIC_API_KEY (LLM_CLIENT_MODE=live)."""

    def __init__(self):
        import anthropic

        settings = get_settings()
        self._model = settings.anthropic_model
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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

    def chat(self, system: str, messages: list[dict]) -> str:
        response = self._client.messages.create(
            model=self._model, max_tokens=2048, system=system, messages=messages
        )
        if response.stop_reason == "refusal":
            return '{"tool": "finish", "args": {"answer": "declined", "citations": []}}'
        return next((b.text for b in response.content if b.type == "text"), "")


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"```$", "", stripped.strip())
    return stripped


def get_llm_client() -> LLMClient:
    if get_settings().llm_client_mode == "live":
        return AnthropicLLMClient()
    return MockLLMClient()
