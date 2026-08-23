"""Pairwise scoring (report 4.5): compares two candidate records on name
similarity (and, when present, shared attributes) to produce a 0-1
confidence that they're the same real-world entity.
"""

from __future__ import annotations

import jellyfish
from rapidfuzz import fuzz

NAME_WEIGHT = 0.6
JARO_WEIGHT = 0.3
ATTR_WEIGHT = 0.1


def score_pair(name_a: str, name_b: str, attrs_a: dict | None = None, attrs_b: dict | None = None) -> float:
    token_sort = fuzz.token_sort_ratio(name_a, name_b) / 100.0
    jaro = jellyfish.jaro_winkler_similarity(name_a.lower(), name_b.lower())

    # Weight normalizes over only the components that actually have data, so an
    # exact name match can still reach 1.0 when no shared attributes exist —
    # otherwise the attribute weight is dead weight that caps every score
    # below any threshold expecting a perfect match to hit 1.0.
    components = [(NAME_WEIGHT, token_sort), (JARO_WEIGHT, jaro)]
    attrs_a, attrs_b = attrs_a or {}, attrs_b or {}
    shared_keys = set(attrs_a) & set(attrs_b)
    if shared_keys:
        matches = sum(1 for k in shared_keys if str(attrs_a[k]).lower() == str(attrs_b[k]).lower())
        components.append((ATTR_WEIGHT, matches / len(shared_keys)))

    total_weight = sum(weight for weight, _ in components)
    return sum(weight * value for weight, value in components) / total_weight
