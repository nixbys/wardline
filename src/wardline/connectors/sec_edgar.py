"""SEC EDGAR connector — US public company filings, government open data.

Uses the documented `data.sec.gov`/`www.sec.gov` endpoints directly, with the
SEC-mandated descriptive User-Agent header and a conservative per-request
delay (SEC's fair-access guidance: stay well under ~10 req/s).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
LICENSE = "us-gov-open-data"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("sec_edgar")
class SecEdgarConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot contact@example.com"
        )
        self._delay_seconds = float(self.config.get("delay_seconds", 0.2))

    @_retry
    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def discover(
        self, ciks: list[str] | None = None, forms: list[str] | None = None, limit_per_cik: int = 5
    ) -> AsyncIterator[SourceItem]:
        if not ciks:
            return
        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(headers=headers) as client:
            for cik in ciks:
                padded = cik.zfill(10)
                data = await self._get_json(client, SUBMISSIONS_URL.format(cik=padded))
                await asyncio.sleep(self._delay_seconds)
                recent = data.get("filings", {}).get("recent", {})
                company_name = data.get("name", padded)
                count = 0
                for i, accession in enumerate(recent.get("accessionNumber", [])):
                    form = recent["form"][i]
                    if forms and form not in forms:
                        continue
                    if count >= limit_per_cik:
                        break
                    count += 1
                    yield SourceItem(
                        ref=f"{padded}/{accession}/{recent['primaryDocument'][i]}",
                        hint_title=f"{company_name} {form} ({recent['filingDate'][i]})",
                        extra={
                            "cik": padded,
                            "company_name": company_name,
                            "form": form,
                            "filing_date": recent["filingDate"][i],
                            "accession": accession,
                        },
                    )

    async def fetch(self, item: SourceItem) -> RawObject:
        cik, accession, primary_doc = item.ref.split("/", 2)
        accession_nodash = accession.replace("-", "")
        url = f"{ARCHIVES_BASE}/{int(cik)}/{accession_nodash}/{primary_doc}"
        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await self._fetch_with_retry(client, url)
        content_type = "application/pdf" if primary_doc.lower().endswith(".pdf") else "text/html"
        return RawObject(
            uri=url,
            content=resp.content,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            extra=item.extra,
        )

    @_retry
    async def _fetch_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        return resp

    def parse(self, raw: RawObject) -> ParsedDocument:
        if raw.content_type == "application/pdf":
            from wardline.ingestion.extractors.pdf import extract_pdf

            extracted = extract_pdf(raw.content)
            text = extracted.text
        else:
            from wardline.ingestion.extractors.html import extract_html

            extracted = extract_html(raw.content, url=raw.uri)
            text = extracted.text

        published_at = None
        if raw.extra.get("filing_date"):
            published_at = datetime.fromisoformat(raw.extra["filing_date"]).replace(tzinfo=UTC)

        title = f"{raw.extra.get('company_name', 'Unknown')} — {raw.extra.get('form', 'filing')}"
        return ParsedDocument(
            uri=raw.uri,
            title=title,
            text=text,
            lang="en",
            published_at=published_at,
            extra={"cik": raw.extra.get("cik"), "form": raw.extra.get("form")},
        )
