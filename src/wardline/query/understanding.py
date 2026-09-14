"""Query understanding (report 5.5 step 1): extract simple date constraints
from the question so retrieval can filter by `published_after`/
`published_before`. Full entity resolution against the knowledge graph
happens in graph/repository.py once mode="auto" routes there (Phase 5).

Deliberately regex-heuristic, not NLP -- matches this module's existing
scope. `published_before` is exclusive (see retrieval/lexical.py's
half-open-range comment): "before 2020" means before Jan 1 2020, exactly
as read. "Between 2020 and 2023" needs the one adjustment this implies --
its exclusive upper bound is Jan 1 2024, not Jan 1 2023, so the range
actually includes all of the stated end year rather than excluding it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

_YEAR_SINCE_RE = re.compile(r"\b(?:since|after)\s+(\d{4})\b", re.IGNORECASE)
_YEAR_BEFORE_RE = re.compile(r"\bbefore\s+(\d{4})\b", re.IGNORECASE)
_YEAR_RANGE_RE = re.compile(r"\bbetween\s+(\d{4})\s+and\s+(\d{4})\b", re.IGNORECASE)


def extract_constraints(question: str) -> dict:
    constraints: dict = {}

    range_match = _YEAR_RANGE_RE.search(question)
    if range_match:
        start_year, end_year = sorted(int(y) for y in range_match.groups())
        constraints["published_after"] = datetime(start_year, 1, 1, tzinfo=UTC)
        constraints["published_before"] = datetime(end_year + 1, 1, 1, tzinfo=UTC)
        return constraints  # a range match is unambiguous -- no need to also check since/before

    since_match = _YEAR_SINCE_RE.search(question)
    if since_match:
        constraints["published_after"] = datetime(int(since_match.group(1)), 1, 1, tzinfo=UTC)

    before_match = _YEAR_BEFORE_RE.search(question)
    if before_match:
        constraints["published_before"] = datetime(int(before_match.group(1)), 1, 1, tzinfo=UTC)

    return constraints


def coerce_date_filters(filters: dict) -> dict:
    """`published_after`/`published_before` arrive as ISO strings from any
    caller that isn't Python code building the dict directly -- a
    QueryRequest.filters value (typed dict[str, str]), or a live LLM's
    JSON tool-call args in agent/loop.py. Postgres's own `CAST(... AS
    timestamptz)` (retrieval/lexical.py, vector.py) would likely parse an
    ISO string fine without this, but coercing here fails fast and clearly
    on a malformed date instead of surfacing a confusing SQL error deep in
    a retrieval call.
    """
    coerced = dict(filters)
    for key in ("published_after", "published_before"):
        if isinstance(coerced.get(key), str):
            coerced[key] = datetime.fromisoformat(coerced[key])
    return coerced
