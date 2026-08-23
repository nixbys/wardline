"""Agent loop guardrails (report 5.8): hard step/token budgets, retrieval
dedup, and a mandatory-citation requirement on `finish` — the controls that
keep an agentic loop from running forever or asserting an unsupported claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class AgentBudget:
    max_steps: int
    max_total_tokens: int
    steps_used: int = 0
    tokens_used: int = 0
    _seen_calls: set[str] = field(default_factory=set)

    def steps_exhausted(self) -> bool:
        return self.steps_used >= self.max_steps

    def tokens_exhausted(self) -> bool:
        return self.tokens_used >= self.max_total_tokens

    def record_step(self, tokens: int) -> None:
        self.steps_used += 1
        self.tokens_used += tokens

    def is_duplicate_call(self, tool: str, args: dict) -> bool:
        key = f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in self._seen_calls:
            return True
        self._seen_calls.add(key)
        return False


def estimate_tokens(text: str) -> int:
    """Cheap word-count proxy — good enough for a budget guardrail, not billing."""
    return max(1, len(text.split()))
