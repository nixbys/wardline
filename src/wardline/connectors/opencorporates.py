"""OpenCorporates connector — company registry data outside SEC EDGAR's US-
public-filer scope (private companies, non-US jurisdictions, officers).

OpenCorporates now requires an API token for every endpoint, including
search (verified live: even /v0.4/jurisdictions 401s without one) — this
connector could not be live-verified this session. Set
OPENCORPORATES_API_TOKEN before running it; see
https://opencorporates.com/api_accounts/new for the free non-commercial tier.

Data is licensed ODbL (Open Database License) by OpenCorporates — share-alike
attribution required for redistribution, distinct from SEC EDGAR's
us-gov-open-data tag.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

API_BASE = "https://api.opencorporates.com/v0.4"
LICENSE = "odbl-opencorporates"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("opencorporates")
class OpenCorporatesConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )
        self._api_token = self.config.get("api_token")

    def _auth_params(self) -> dict:
        if not self._api_token:
            raise ValueError(
                "opencorporates connector requires an api_token "
                "(OPENCORPORATES_API_TOKEN / config['api_token'])"
            )
        return {"api_token": self._api_token}

    @_retry
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        resp = await client.get(f"{API_BASE}{path}", params={**params, **self._auth_params()}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def discover(
        self,
        company_refs: list[str] | None = None,  # "{jurisdiction_code}/{company_number}"
        search: str | None = None,
        jurisdiction_code: str | None = None,
        limit: int = 10,
    ) -> AsyncIterator[SourceItem]:
        if company_refs:
            for ref in company_refs:
                yield SourceItem(ref=ref)
            return
        if search:
            async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
                params = {"q": search, "per_page": str(limit)}
                if jurisdiction_code:
                    params["jurisdiction_code"] = jurisdiction_code
                resp = await self._get(client, "/companies/search", params)
                for result in resp.get("results", {}).get("companies", []):
                    company = result["company"]
                    ref = f"{company['jurisdiction_code']}/{company['company_number']}"
                    yield SourceItem(ref=ref, hint_title=company.get("name"))

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            resp = await self._get(client, f"/companies/{item.ref}", {})
            company = resp["results"]["company"]

        sentences = [f"{company['name']} is a company registered in {company.get('jurisdiction_code', 'unknown jurisdiction')}."]
        if company.get("company_type"):
            sentences.append(f"{company['name']} is registered as a {company['company_type']}.")
        if company.get("incorporation_date"):
            sentences.append(f"{company['name']} was incorporated on {company['incorporation_date']}.")
        if company.get("current_status"):
            sentences.append(f"{company['name']}'s current registration status is {company['current_status']}.")
        registered_address = company.get("registered_address_in_full")
        if registered_address:
            sentences.append(f"{company['name']}'s registered address is {registered_address}.")
        for officer in company.get("officers", []) or []:
            officer_data = officer.get("officer", officer)
            name = officer_data.get("name")
            position = officer_data.get("position")
            if name and position:
                sentences.append(f"{name} is a {position} of {company['name']}.")

        text = " ".join(sentences)
        canonical_url = company.get("opencorporates_url") or f"https://opencorporates.com/companies/{item.ref}"
        return RawObject(
            uri=canonical_url,
            content=text.encode("utf-8"),
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
            extra={"name": company.get("name")},
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        return ParsedDocument(
            uri=raw.uri,
            title=raw.extra.get("name") or raw.uri,
            text=raw.content.decode("utf-8"),
            lang="en",
            published_at=None,
            extra={"attribution": f"{raw.extra.get('name')} — OpenCorporates, ODbL, {raw.uri}"},
        )
