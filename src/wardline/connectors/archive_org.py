"""Internet Archive Wayback Machine connector.

Retrieves historical snapshots of already-public web pages via the Wayback
CDX API (snapshot index) and the standard `web.archive.org/web/{timestamp}/{url}`
replay endpoint — both public, unauthenticated, rate-limit-friendly APIs. No
scanning, no interception: this only ever asks archive.org for a copy of a
page it already crawled and published itself, the same way a browser would.

Useful for point-in-time citations (what did this page say on date X) and for
recovering sources that have since gone offline or been edited.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

CDX_API = "https://web.archive.org/cdx/search/cdx"
LICENSE = "public-archive-snapshot"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("archive_org")
class ArchiveOrgConnector(Connector):
    """Snapshot license note: a Wayback capture is a copy of what the
    original site published; rights remain with the original publisher.
    `default_license` here tags provenance/handling, not a redistribution
    grant — same convention this repo already uses for `web_crawler`'s
    `open-web-crawled` tag.
    """

    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )

    @_retry
    async def _get(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
        resp = await client.get(url, params=params, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp

    async def discover(
        self,
        urls: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 10,
    ) -> AsyncIterator[SourceItem]:
        if not urls:
            return
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            for original_url in urls:
                params = {
                    "url": original_url,
                    "output": "json",
                    "filter": "statuscode:200",
                    "collapse": "timestamp:8",  # at most one snapshot per day
                    "limit": str(limit),
                }
                if from_date:
                    params["from"] = from_date
                if to_date:
                    params["to"] = to_date
                resp = await self._get(client, CDX_API, params=params)
                rows = resp.json()
                if len(rows) < 2:
                    continue  # header row only, or no snapshots found
                header, *snapshots = rows
                for row in snapshots:
                    record = dict(zip(header, row, strict=True))
                    timestamp = record["timestamp"]
                    snapshot_url = f"https://web.archive.org/web/{timestamp}/{original_url}"
                    yield SourceItem(
                        ref=snapshot_url,
                        extra={"original_url": original_url, "timestamp": timestamp},
                    )

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            resp = await self._get(client, item.ref)
            timestamp = item.extra.get("timestamp")
            published_at = None
            if timestamp:
                published_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            return RawObject(
                uri=item.ref,
                content=resp.content,
                content_type="text/html",
                fetched_at=datetime.now(UTC),
                extra={
                    "original_url": item.extra.get("original_url"),
                    "timestamp": timestamp,
                    "published_at": published_at.isoformat() if published_at else None,
                },
            )

    def parse(self, raw: RawObject) -> ParsedDocument:
        from wardline.ingestion.extractors.html import extract_html

        extracted = extract_html(raw.content, url=raw.extra.get("original_url") or raw.uri)
        published_at = None
        if raw.extra.get("published_at"):
            published_at = datetime.fromisoformat(raw.extra["published_at"])
        return ParsedDocument(
            uri=raw.uri,
            title=extracted.title or raw.extra.get("original_url") or raw.uri,
            text=extracted.text,
            lang="en",
            published_at=published_at,
            extra={
                "original_url": raw.extra.get("original_url"),
                "wayback_timestamp": raw.extra.get("timestamp"),
                "attribution": f"Internet Archive Wayback Machine snapshot of {raw.extra.get('original_url')}",
            },
        )
