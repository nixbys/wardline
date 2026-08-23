"""Relation extraction (report 4.5 step 3): dependency-parse-based pattern
matching over NER mentions.

Earlier versions of this module used a sentence-scoped keyword trigger
alone: any sentence containing "founded" linked *every* Person mention in
that sentence to *every* Organization mention in it, regardless of who the
verb's actual subject and object were. That produced real false positives
whenever a trigger sentence mentioned more than one person or org for any
reason (an aside, a second company named in passing, an advisor mentioned
in the same breath as a founder).

This version keeps the same cheap keyword filter to decide which sentences
are worth parsing, then walks spaCy's dependency tree from the matched
trigger token(s) to find the verb's real syntactic arguments: nsubj/
nsubjpass/agent/dobj, following `conj` coordination ("Alice and Bob
founded..."), inheriting the subject across a `conj`-chained verb pair
("co - founded" tokenizes as two coordinated verbs under the small model),
and resolving the antecedent of a relative clause ("Carol, who founded
X..."). For the two nominal patterns (SUBSIDIARY_OF's "a subsidiary of X"
/ "owned by X") it walks the `prep`/`pobj` and `nsubj`/`attr` chain
instead of pairing whichever orgs happen to co-occur.

The small model's parser still occasionally mangles a hyphenated
"co-founded" immediately after a *single* proper-noun subject (a known
tokenization weak spot); rather than silently losing that recall, a
narrowly-scoped fallback fires only when the sentence has exactly one
candidate on each side (so there is nothing for it to conflate -- the
failure mode this module exists to avoid only arises with multiple
candidates on a side).

This is narrower than a full open-domain relation extractor, but real
dependency parsing, not a keyword-only heuristic -- scoped to the handful
of relation types the report's own worked example needs (FOUNDED,
CO_FOUNDED_WITH, SUBSIDIARY_OF, ACQUIRED). An LLM-assist call would refine
ambiguous cases in `live` LLM mode; skipped in `mock` mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import spacy
from spacy.tokens import Token

from wardline.graph.ner import Mention

_FOUNDED_TRIGGERS = ("founded", "co-founded", "cofounded", "started the company", "established")
_COFOUNDER_TRIGGERS = ("co-founder", "cofounder", "co-founded", "cofounded")
_SUBSIDIARY_TRIGGERS = ("subsidiary of", "owned by", "a unit of", "division of")
_ACQUIRED_TRIGGERS = ("acquired", "acquisition of", "bought")

# Includes the small model's actual (occasionally odd, e.g. "cofounde")
# lemmatization of "cofounded"/"co-founded" fragments, pinned to the
# en_core_web_sm version this project installs.
_FOUNDED_LEMMAS = {"found", "establish", "cofound", "cofounde"}
_ACQUIRED_LEMMAS = {"acquire", "buy"}
_OWN_LEMMAS = {"own"}
_SUBSIDIARY_NOUNS = {"subsidiary", "unit", "division"}


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


def _mention_for_token(token: Token, mentions: list[Mention]) -> Mention | None:
    """The mention (if any) whose character span contains this token."""
    for m in mentions:
        if m.span_start <= token.idx < m.span_end:
            return m
    return None


def _arg_mentions(token: Token, deps: tuple[str, ...], mentions: list[Mention]) -> list[Mention]:
    """Mentions attached to `token` via one of `deps`, following `conj`
    coordination so "Alice and Bob founded X" yields both Alice and Bob.
    """
    out: list[Mention] = []
    for child in token.children:
        if child.dep_ not in deps:
            continue
        for t in (child, *child.conjuncts):
            m = _mention_for_token(t, mentions) or _mention_for_token(t.head, mentions)
            if m is not None and m not in out:
                out.append(m)
    return out


def _verb_subjects(tok: Token, mentions: list[Mention], _depth: int = 0) -> list[Mention]:
    """A verb's subject, handling three cases the raw nsubj/nsubjpass
    children miss: coordinated verbs sharing one subject ("co - founded"
    splits into two `conj`-linked verb tokens under the small model), and
    relative-clause antecedents ("Carol, who founded X" -- "who" isn't a
    named entity, but the clause's head is Carol).
    """
    direct = _arg_mentions(tok, ("nsubj", "nsubjpass"), mentions)
    if direct:
        return direct
    if _depth < 3 and tok.dep_ == "conj":
        return _verb_subjects(tok.head, mentions, _depth + 1)
    if tok.dep_ == "relcl":
        antecedent = _mention_for_token(tok.head, mentions)
        if antecedent is not None:
            return [antecedent]
    return []


def _agent_mentions(tok: Token, mentions: list[Mention]) -> list[Mention]:
    return [
        m
        for child in tok.children
        if child.dep_ == "agent"
        for m in _arg_mentions(child, ("pobj",), mentions)
    ]


def _pairs(sources: list[Mention], targets: list[Mention], want_from: str, want_to: str):
    for s in sources:
        if s.ner_type != want_from:
            continue
        for t in targets:
            if t.ner_type != want_to or t is s:
                continue
            yield s, t


def _person_pairs(people: list[Mention]):
    for i, a in enumerate(people):
        for b in people[i + 1 :]:
            yield a, b


def extract_relations(text: str, mentions: list[Mention]) -> list[RelationCandidate]:
    doc = _model()(text)
    candidates: list[RelationCandidate] = []

    for sent in doc.sents:
        sentence_lower = sent.text.lower()
        sentence_mentions = _mentions_in_span(mentions, sent.start_char, sent.end_char)
        if not sentence_mentions:
            continue

        has_founded = any(t in sentence_lower for t in _FOUNDED_TRIGGERS)
        has_cofounder = any(t in sentence_lower for t in _COFOUNDER_TRIGGERS)
        has_subsidiary = any(t in sentence_lower for t in _SUBSIDIARY_TRIGGERS)
        has_acquired = any(t in sentence_lower for t in _ACQUIRED_TRIGGERS)
        if not (has_founded or has_cofounder or has_subsidiary or has_acquired):
            continue

        sentence_people = [m for m in sentence_mentions if m.ner_type == "Person"]
        sentence_orgs = [m for m in sentence_mentions if m.ner_type == "Organization"]
        found_founded = False
        found_acquired = False

        for tok in sent:
            # --- FOUNDED / CO_FOUNDED_WITH: verb "found"/"establish" -----
            if (has_founded or has_cofounder) and tok.lemma_ in _FOUNDED_LEMMAS:
                founders = _verb_subjects(tok, sentence_mentions) or _agent_mentions(
                    tok, sentence_mentions
                )
                objects = _arg_mentions(tok, ("dobj", "attr", "oprd"), sentence_mentions)
                if has_founded:
                    for person, org in _pairs(founders, objects, "Person", "Organization"):
                        candidates.append(RelationCandidate(person, org, "FOUNDED", 0.85, sent.text))
                        found_founded = True
                founder_people = [m for m in founders if m.ner_type == "Person"]
                if has_cofounder and len(founder_people) > 1:
                    for a, b in _person_pairs(founder_people):
                        candidates.append(
                            RelationCandidate(a, b, "CO_FOUNDED_WITH", 0.8, sent.text)
                        )

            # --- ACQUIRED: verb "acquire"/"buy" (active + passive) -------
            if has_acquired and tok.lemma_ in _ACQUIRED_LEMMAS:
                buyers = _arg_mentions(tok, ("nsubj",), sentence_mentions)
                targets = _arg_mentions(tok, ("dobj",), sentence_mentions)
                for buyer, target in _pairs(buyers, targets, "Organization", "Organization"):
                    candidates.append(RelationCandidate(target, buyer, "ACQUIRED", 0.8, sent.text))
                    found_acquired = True
                passive_targets = _arg_mentions(tok, ("nsubjpass",), sentence_mentions)
                passive_buyers = _agent_mentions(tok, sentence_mentions)
                for buyer, target in _pairs(
                    passive_buyers, passive_targets, "Organization", "Organization"
                ):
                    candidates.append(RelationCandidate(target, buyer, "ACQUIRED", 0.8, sent.text))
                    found_acquired = True

            # --- SUBSIDIARY_OF: "X, a subsidiary/unit/division of Y" -----
            if has_subsidiary and tok.lemma_ in _SUBSIDIARY_NOUNS:
                parents = [
                    m
                    for child in tok.children
                    if child.dep_ == "prep" and child.lemma_ == "of"
                    for m in _arg_mentions(child, ("pobj",), sentence_mentions)
                ]
                head_mention = _mention_for_token(tok.head, sentence_mentions)
                children = [head_mention] if head_mention is not None else []
                children += _arg_mentions(tok.head, ("nsubj", "appos"), sentence_mentions)
                for child_org, parent_org in _pairs(
                    children, parents, "Organization", "Organization"
                ):
                    candidates.append(
                        RelationCandidate(child_org, parent_org, "SUBSIDIARY_OF", 0.75, sent.text)
                    )

            # --- SUBSIDIARY_OF (passive): "X is owned by Y" --------------
            if has_subsidiary and tok.lemma_ in _OWN_LEMMAS:
                owned = _arg_mentions(tok, ("nsubjpass",), sentence_mentions)
                owners = _agent_mentions(tok, sentence_mentions)
                for child_org, parent_org in _pairs(owned, owners, "Organization", "Organization"):
                    candidates.append(
                        RelationCandidate(child_org, parent_org, "SUBSIDIARY_OF", 0.75, sent.text)
                    )

        # Narrowly-scoped fallback: the small model's parser occasionally
        # mangles "<Name> co-founded <Org>" (single subject, hyphenated
        # verb) badly enough that no dependency arc survives. Only step in
        # when the sentence has exactly one person and one org candidate --
        # there is nothing to conflate, so this can't reintroduce the
        # blind-cartesian-product false positives this module replaces.
        if has_founded and not found_founded and len(sentence_people) == 1 and len(sentence_orgs) == 1:
            candidates.append(
                RelationCandidate(sentence_people[0], sentence_orgs[0], "FOUNDED", 0.6, sent.text)
            )
        if has_acquired and not found_acquired and len(sentence_orgs) == 2:
            a, b = sentence_orgs
            candidates.append(RelationCandidate(a, b, "ACQUIRED", 0.55, sent.text))

    # de-duplicate identical (from, to, type) triples the different patterns
    # above can independently rediscover in one sentence.
    seen: set[tuple[int, int, str, int, int]] = set()
    deduped: list[RelationCandidate] = []
    for c in candidates:
        key = (
            c.from_mention.span_start,
            c.from_mention.span_end,
            c.type,
            c.to_mention.span_start,
            c.to_mention.span_end,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped
