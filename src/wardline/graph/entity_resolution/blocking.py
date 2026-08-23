"""Blocking (report 4.5): cheaply group plausibly-matching records so
resolution doesn't compare all-against-all. Block key = entity type +
metaphone of the first name token — coarse on purpose; scoring.py does the
real discrimination within a block.
"""

from __future__ import annotations

import jellyfish


def block_key(entity_type: str, canonical_name: str) -> str:
    first_token = canonical_name.strip().split()[0] if canonical_name.strip() else ""
    return f"{entity_type}:{jellyfish.metaphone(first_token)}"
