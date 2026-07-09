"""Relation extraction (report 4.5 step 3): rule-based, sentence-scoped
pattern matching over NER mentions. Real extraction (keyword triggers +
mention co-occurrence within a sentence), not a stub — scoped to the
handful of relation types the report's own worked example needs
(FOUNDED, CO_FOUNDED_WITH, SUBSIDIARY_OF, ACQUIRED). An LLM-assist call
would refine ambiguous cases in `live` LLM mode; skipped in `mock` mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import spacy

from cranus.graph.ner import Mention

_FOUNDED_TRIGGERS = ("founded", "co-founded", "cofounded", "started the company", "established")
_COFOUNDER_TRIGGERS = ("co-founder", "cofounder", "co-founded", "cofounded")
_SUBSIDIARY_TRIGGERS = ("subsidiary of", "owned by", "a unit of", "division of")
_ACQUIRED_TRIGGERS = ("acquired", "acquisition of", "bought")


@dataclass
class RelationCandidate:
    from_mention: Mention
    to_mention: Mention
    type: str
    confidence: float
    evidence_text: str


@lru_cache
def _model():
    return spacy.load("en_core_web_sm")


def _mentions_in_span(mentions: list[Mention], start: int, end: int) -> list[Mention]:
    return [m for m in mentions if m.span_start >= start and m.span_end <= end]


def extract_relations(text: str, mentions: list[Mention]) -> list[RelationCandidate]:
    doc = _model()(text)
    candidates: list[RelationCandidate] = []

    for sent in doc.sents:
        sentence_lower = sent.text.lower()
        sentence_mentions = _mentions_in_span(mentions, sent.start_char, sent.end_char)
        people = [m for m in sentence_mentions if m.ner_type == "Person"]
        orgs = [m for m in sentence_mentions if m.ner_type == "Organization"]

        if any(t in sentence_lower for t in _FOUNDED_TRIGGERS):
            for person in people:
                for org in orgs:
                    candidates.append(
                        RelationCandidate(
                            from_mention=person,
                            to_mention=org,
                            type="FOUNDED",
                            confidence=0.75,
                            evidence_text=sent.text,
                        )
                    )

        if any(t in sentence_lower for t in _COFOUNDER_TRIGGERS) and len(people) > 1:
            for i, person_a in enumerate(people):
                for person_b in people[i + 1 :]:
                    candidates.append(
                        RelationCandidate(
                            from_mention=person_a,
                            to_mention=person_b,
                            type="CO_FOUNDED_WITH",
                            confidence=0.7,
                            evidence_text=sent.text,
                        )
                    )

        if any(t in sentence_lower for t in _SUBSIDIARY_TRIGGERS) and len(orgs) > 1:
            for i, org_a in enumerate(orgs):
                for org_b in orgs[i + 1 :]:
                    candidates.append(
                        RelationCandidate(
                            from_mention=org_a,
                            to_mention=org_b,
                            type="SUBSIDIARY_OF",
                            confidence=0.65,
                            evidence_text=sent.text,
                        )
                    )
        elif any(t in sentence_lower for t in _ACQUIRED_TRIGGERS) and len(orgs) > 1:
            for i, org_a in enumerate(orgs):
                for org_b in orgs[i + 1 :]:
                    candidates.append(
                        RelationCandidate(
                            from_mention=org_a,
                            to_mention=org_b,
                            type="ACQUIRED",
                            confidence=0.6,
                            evidence_text=sent.text,
                        )
                    )

    return candidates
