"""Retrieval planner (report 5.5 step 2): decides which sub-questions need
text retrieval vs. graph lookup vs. both.
"""

from __future__ import annotations

from wardline.query.llm_client import LLMClient, SubQuestion


def plan(llm: LLMClient, question: str) -> list[SubQuestion]:
    return llm.decompose(question)
