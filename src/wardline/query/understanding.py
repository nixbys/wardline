"""Query understanding (report 5.5 step 1): extract simple date constraints
from the question so retrieval can filter by `published_after`. Full entity
resolution against the knowledge graph happens in graph/repository.py once
mode="auto" routes there (Phase 5).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

_YEAR_SINCE_RE = re.compile(r"\b(?:since|after)\s+(\d{4})\b", re.IGNORECASE)


def extract_constraints(question: str) -> dict:
    constraints: dict = {}
    match = _YEAR_SINCE_RE.search(question)
    if match:
        year = int(match.group(1))
        constraints["published_after"] = datetime(year, 1, 1, tzinfo=UTC)
    return constraints
