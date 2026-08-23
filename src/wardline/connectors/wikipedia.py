"""Wikipedia connector — direct MediaWiki Action API calls (not the
unmaintained `wikipedia` pip package), so we control provenance precisely.
License is always CC-BY-SA-4.0 with the required attribution captured in
`ParsedDocument.extra`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

API_BASE = "https://en.wikipedia.org/w/api.php"
LICENSE = "CC-BY-SA-4.0"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("wikipedia")
class WikipediaConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )

    async def discover(
        self, titles: list[str] | None = None, search: str | None = None, limit: int = 20
    ) -> AsyncIterator[SourceItem]:
        if titles:
            for title in titles:
                yield SourceItem(ref=title)
            return
        if search:
            async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
                resp = await self._get(
                    client,
                    {
                        "action": "query",
                        "list": "search",
                        "srsearch": search,
                        "srlimit": str(limit),
                        "format": "json",
                    },
                )
                for hit in resp["query"]["search"]:
                    yield SourceItem(ref=hit["title"])

    @_retry
    async def _get(self, client: httpx.AsyncClient, params: dict) -> dict:
        resp = await client.get(API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            parse_resp = await self._get(
                client,
                {
                    "action": "parse",
                    "page": item.ref,
                    "prop": "text|revid",
                    "format": "json",
                    "formatversion": "2",
                },
            )
            if "error" in parse_resp:
                raise ValueError(f"Wikipedia parse failed for {item.ref!r}: {parse_resp['error']}")
            page = parse_resp["parse"]
            html_fragment = page["text"]
            page_id = page["pageid"]
            revid = page["revid"]

            info_resp = await self._get(
                client,
                {
                    "action": "query",
                    "pageids": str(page_id),
                    "prop": "revisions|info",
                    "rvprop": "timestamp",
                    "inprop": "url",
                    "format": "json",
                    "formatversion": "2",
                },
            )
            page_info = info_resp["query"]["pages"][0]
            revision_ts = page_info["revisions"][0]["timestamp"]
            canonical_url = page_info["fullurl"]

        html = f"<html><body>{html_fragment}</body></html>"
        return RawObject(
            uri=canonical_url,
            content=html.encode("utf-8"),
            content_type="text/html",
            fetched_at=datetime.now(UTC),
            extra={
                "title": page["title"],
                "revid": revid,
                "published_at": revision_ts,
                "attribution": f"{page['title']} — Wikipedia contributors, CC BY-SA 4.0, {canonical_url}",
            },
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        from wardline.ingestion.extractors.html import extract_html

        extracted = extract_html(raw.content)
        published_at = None
        if raw.extra.get("published_at"):
            published_at = datetime.fromisoformat(raw.extra["published_at"])
        return ParsedDocument(
            uri=raw.uri,
            title=raw.extra.get("title") or extracted.title or raw.uri,
            text=extracted.text,
            lang="en",
            published_at=published_at,
            extra={"attribution": raw.extra.get("attribution")},
        )
