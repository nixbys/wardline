"""Autonomous lawful web crawler connector.

This is real, unattended data acquisition: given seed URLs, it follows links
within allowed domains up to a depth/page budget, honoring `robots.txt` and a
per-domain politeness delay, and yields every page it's allowed to fetch.

This is deliberately NOT the illegal thing: it only ever requests pages a
site's own robots.txt says are open to crawlers, over plain HTTP(S), the same
way a search-engine crawler or a browser would — no interception of traffic
that isn't addressed to it, no bypassing auth, no touching anything private.
"""

from __future__ import annotations

import asyncio
import urllib.robotparser
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
import tenacity

from wardline.common.logging import get_logger
from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

logger = get_logger(__name__)
LICENSE = "open-web-crawled"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    reraise=True,
)


@register_connector("web_crawler")
class WebCrawlerConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )
        self._per_domain_delay = float(self.config.get("per_domain_delay_seconds", 1.0))
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._page_cache: dict[str, bytes] = {}
        self._last_fetch_at: dict[str, float] = {}

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc

    async def _robots_allows(self, client: httpx.AsyncClient, url: str) -> bool:
        domain = self._domain(url)
        if domain not in self._robots_cache:
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            parser = urllib.robotparser.RobotFileParser()
            try:
                resp = await client.get(robots_url, timeout=10)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    parser.allow_all = True
            except httpx.HTTPError:
                parser.allow_all = True
            self._robots_cache[domain] = parser
        parser = self._robots_cache[domain]
        return getattr(parser, "allow_all", False) or parser.can_fetch(self._user_agent, url)

    async def _politeness_wait(self, url: str) -> None:
        domain = self._domain(url)
        loop = asyncio.get_event_loop()
        last = self._last_fetch_at.get(domain)
        if last is not None:
            elapsed = loop.time() - last
            if elapsed < self._per_domain_delay:
                await asyncio.sleep(self._per_domain_delay - elapsed)
        self._last_fetch_at[domain] = loop.time()

    @_retry
    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        resp = await client.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return resp

    async def discover(
        self,
        seeds: list[str] | None = None,
        allowed_domains: list[str] | None = None,
        max_depth: int = 2,
        max_pages: int = 50,
    ) -> AsyncIterator[SourceItem]:
        if not seeds:
            return
        allowed = set(allowed_domains) if allowed_domains else {self._domain(s) for s in seeds}
        seen: set[str] = set()
        queue: list[tuple[str, int]] = [(s, 0) for s in seeds]
        emitted = 0

        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            while queue and emitted < max_pages:
                url, depth = queue.pop(0)
                if url in seen or self._domain(url) not in allowed:
                    continue
                seen.add(url)

                if not await self._robots_allows(client, url):
                    logger.info("crawler.robots_disallowed", url=url)
                    continue

                await self._politeness_wait(url)
                try:
                    resp = await self._get(client, url)
                except httpx.HTTPError as exc:
                    logger.info("crawler.fetch_failed", url=url, error=str(exc))
                    continue

                if "text/html" not in resp.headers.get("content-type", ""):
                    continue

                self._page_cache[url] = resp.content
                emitted += 1
                yield SourceItem(ref=url)

                if depth < max_depth:
                    for link in self._extract_links(resp.text, url):
                        if link not in seen:
                            queue.append((link, depth + 1))

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        import re

        hrefs = re.findall(r'href=["\']([^"\'#]+)["\']', html, flags=re.IGNORECASE)
        links = []
        for href in hrefs:
            absolute = urljoin(base_url, href)
            if absolute.startswith("http"):
                links.append(absolute.split("#")[0])
        return links

    async def fetch(self, item: SourceItem) -> RawObject:
        content = self._page_cache.get(item.ref)
        if content is None:
            async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
                if not await self._robots_allows(client, item.ref):
                    raise PermissionError(f"robots.txt disallows fetching {item.ref}")
                resp = await self._get(client, item.ref)
                content = resp.content
        return RawObject(
            uri=item.ref,
            content=content,
            content_type="text/html",
            fetched_at=datetime.now(UTC),
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        from wardline.ingestion.extractors.html import extract_html

        extracted = extract_html(raw.content, url=raw.uri)
        return ParsedDocument(
            uri=raw.uri,
            title=extracted.title or raw.uri,
            text=extracted.text,
            lang="en",
            published_at=None,
            extra={},
        )
