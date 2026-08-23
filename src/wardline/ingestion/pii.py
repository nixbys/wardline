"""PII tagging at ingestion (report 4.2): label personal-data spans so
downstream ABAC (governance/abac.py) can govern access to them. Regex-based
and deliberately fast — full NER-based entity tagging happens later in the
knowledge & fusion plane (graph/ner.py); this pass only needs to flag the
handful of PII categories access control cares about.
"""

from __future__ import annotations

import re

_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


def tag_pii(text: str) -> list[dict]:
    """Return a list of {"type", "start", "end"} spans for downstream ABAC/redaction."""
    tags: list[dict] = []
    for pii_type, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            tags.append({"type": pii_type, "start": match.start(), "end": match.end()})
    return tags
