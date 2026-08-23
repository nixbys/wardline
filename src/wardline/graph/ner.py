"""Named-entity recognition (report 4.5 step 1): spaCy pipeline over chunk
text. Low-confidence/ambiguous spans would be escalated to an LLM-assist
call in `live` LLM mode; in `mock` mode (this environment) that escalation
is a no-op, so resolution runs on spaCy's own output alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import spacy

# spaCy's generic NER labels -> our light ontology (graph/schema.py ENTITY_TYPES)
_LABEL_MAP = {
    "PERSON": "Person",
    "ORG": "Organization",
    "GPE": "Place",
    "LOC": "Place",
    "PRODUCT": "Product",
    "FAC": "Place",
    "NORP": "Other",
}


@dataclass
class Mention:
    span_text: str
    span_start: int
    span_end: int
    ner_type: str
    confidence: float


@lru_cache
def _model():
    return spacy.load("en_core_web_sm")


def extract_mentions(text: str) -> list[Mention]:
    doc = _model()(text)
    mentions = []
    for ent in doc.ents:
        mapped = _LABEL_MAP.get(ent.label_)
        if mapped is None:
            continue
        mentions.append(
            Mention(
                span_text=ent.text,
                span_start=ent.start_char,
                span_end=ent.end_char,
                ner_type=mapped,
                confidence=0.85,
            )
        )
    return mentions
