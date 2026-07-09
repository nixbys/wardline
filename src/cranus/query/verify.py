"""Citation verification (report 5.5 step 8, the primary anti-hallucination
control): every sentence in the synthesized answer must cite at least one
real, retrieved source ID. Sentences whose citations don't resolve to a
source actually in context are dropped, not silently trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CITATION_RE = re.compile(r"\[([\w\-]+)\]")


@dataclass
class Claim:
    id: str
    text: str
    supported_by: list[str]


@dataclass
class VerifiedAnswer:
    text: str
    claims: list[Claim] = field(default_factory=list)
    confidence: float = 0.0
    insufficient_evidence: bool = False


def verify_citations(raw_answer: str, valid_source_ids: set[str]) -> VerifiedAnswer:
    if not raw_answer.strip():
        return VerifiedAnswer(text="", insufficient_evidence=True)

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(raw_answer) if s.strip()]
    kept_sentences: list[str] = []
    claims: list[Claim] = []

    for sentence in sentences:
        cited_ids = [cid for cid in _CITATION_RE.findall(sentence) if cid in valid_source_ids]
        if not cited_ids:
            continue
        kept_sentences.append(sentence)
        claims.append(Claim(id=f"c{len(claims) + 1}", text=sentence, supported_by=cited_ids))

    if not kept_sentences:
        return VerifiedAnswer(text="", insufficient_evidence=True)

    confidence = len(kept_sentences) / len(sentences) if sentences else 0.0
    return VerifiedAnswer(
        text=" ".join(kept_sentences), claims=claims, confidence=confidence, insufficient_evidence=False
    )
