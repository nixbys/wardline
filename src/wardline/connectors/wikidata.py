"""Wikidata connector — structured facts, not prose.

Wikidata statements (P112 "founded by", P169 "chief executive officer", etc.)
are unambiguous subject-predicate-object triples with no NER/relation-extraction
guesswork required. This connector renders a bounded set of research-relevant
properties into plain declarative sentences ("Airbnb was founded by Brian
Chesky.") and lets them flow through the *existing* ingestion pipeline like any
other document — the sentence-scoped keyword-trigger relation extractor
(graph/relation_extraction.py) already looks for exactly this phrasing, so this
source produces cleaner edges than free-text NER without a new ingestion path.

Content is CC0 (public domain dedication) per Wikidata's terms of use — the
most permissive license tag in this project.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

API_BASE = "https://www.wikidata.org/w/api.php"
LICENSE = "CC0-1.0"

# Bounded to properties relevant to org/people research that the existing
# relation-extraction keyword triggers already recognize (FOUNDED,
# SUBSIDIARY_OF, ACQUIRED-adjacent). Not an attempt to cover all ~11k
# Wikidata properties -- that would be a generic triple-store import, a
# different (and much bigger) feature than this project needs.
#
# Phrasing here is deliberately active-voice / copula-style, not the more
# "natural" passive ("{subject} was founded by {value}."). Verified live
# against the actual spaCy small model in this project (graph/ner.py): it
# reliably tags an org name as ORG in "{value} founded {subject}." but
# regularly misses it as the subject of a passive "was founded by" clause
# in short, terse sentences -- with no ORG mention in the sentence,
# graph/relation_extraction.py's FOUNDED trigger finds a person but no org
# and silently produces zero candidates. P127/P749 collapse to one template
# since they're both "value is {subject}'s parent org" for extraction
# purposes -- keeping two near-identical unreliable phrasings around would
# just be redundant surface area for the same NER failure mode.
_ENTITY_VALUE_TEMPLATES = {
    "P112": "{value} founded {subject}.",
    "P169": "{value} is the chief executive officer of {subject}.",
    "P127": "{value} is the parent organization of {subject}, a subsidiary of {value}.",
    "P749": "{value} is the parent organization of {subject}, a subsidiary of {value}.",
    "P355": "{subject} is the parent organization of {value}, a subsidiary of {subject}.",
    "P159": "{subject} is headquartered in {value}.",
    "P108": "{subject} is employed by {value}.",
}
_TIME_TEMPLATES = {
    "P571": "{subject} was founded in {value}.",
}

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("wikidata")
class WikidataConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )

    @_retry
    async def _get(self, client: httpx.AsyncClient, params: dict) -> dict:
        resp = await client.get(API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def discover(
        self, ids: list[str] | None = None, search: str | None = None, limit: int = 10
    ) -> AsyncIterator[SourceItem]:
        if ids:
            for qid in ids:
                yield SourceItem(ref=qid)
            return
        if search:
            async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
                resp = await self._get(
                    client,
                    {
                        "action": "wbsearchentities",
                        "search": search,
                        "language": "en",
                        "format": "json",
                        "limit": str(limit),
                    },
                )
                for hit in resp.get("search", []):
                    yield SourceItem(ref=hit["id"], hint_title=hit.get("label"))

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            resp = await self._get(
                client,
                {
                    "action": "wbgetentities",
                    "ids": item.ref,
                    "languages": "en",
                    "format": "json",
                    "props": "labels|descriptions|claims",
                },
            )
            entity = resp["entities"].get(item.ref)
            if entity is None or "missing" in entity:
                raise ValueError(f"Wikidata entity not found: {item.ref!r}")

            label = entity.get("labels", {}).get("en", {}).get("value", item.ref)
            description = entity.get("descriptions", {}).get("en", {}).get("value", "")

            referenced_qids: set[str] = set()
            statements: list[tuple[str, str]] = []  # (property, raw value: qid or year)
            for prop in list(_ENTITY_VALUE_TEMPLATES) + list(_TIME_TEMPLATES):
                for claim in entity.get("claims", {}).get(prop, []):
                    datavalue = claim.get("mainsnak", {}).get("datavalue")
                    if not datavalue:
                        continue
                    if prop in _ENTITY_VALUE_TEMPLATES:
                        value_qid = datavalue["value"]["id"]
                        referenced_qids.add(value_qid)
                        statements.append((prop, value_qid))
                    else:
                        year = datavalue["value"]["time"].lstrip("+")[:4]
                        statements.append((prop, year))

            value_labels: dict[str, str] = {}
            if referenced_qids:
                labels_resp = await self._get(
                    client,
                    {
                        "action": "wbgetentities",
                        "ids": "|".join(sorted(referenced_qids)),
                        "languages": "en",
                        "format": "json",
                        "props": "labels",
                    },
                )
                for qid, value_entity in labels_resp["entities"].items():
                    value_labels[qid] = value_entity.get("labels", {}).get("en", {}).get("value", qid)

            sentences = [f"{label} ({description})."] if description else [f"{label}."]
            for prop, raw_value in statements:
                if prop in _ENTITY_VALUE_TEMPLATES:
                    value_text = value_labels.get(raw_value, raw_value)
                    sentences.append(_ENTITY_VALUE_TEMPLATES[prop].format(subject=label, value=value_text))
                else:
                    sentences.append(_TIME_TEMPLATES[prop].format(subject=label, value=raw_value))

            text = " ".join(sentences)
            canonical_url = f"https://www.wikidata.org/wiki/{item.ref}"
            return RawObject(
                uri=canonical_url,
                content=text.encode("utf-8"),
                content_type="text/plain",
                fetched_at=datetime.now(UTC),
                extra={"label": label, "qid": item.ref},
            )

    def parse(self, raw: RawObject) -> ParsedDocument:
        return ParsedDocument(
            uri=raw.uri,
            title=raw.extra.get("label") or raw.uri,
            text=raw.content.decode("utf-8"),
            lang="en",
            published_at=None,
            extra={"attribution": f"{raw.extra.get('label')} — Wikidata, CC0, {raw.uri}"},
        )
