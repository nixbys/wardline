"""USGS earthquake connector — discrete, timestamped, citable public events.

Contrast with `api/routers/globe.py`'s live proxy layers (flights, ships,
satellites, traffic): a continuously-updating position isn't "a source" a
RAG answer can point to, but a specific earthquake at a specific place and
time is exactly that — a fact with a stable USGS event id, the same shape
as a Wikidata statement or an SEC filing. So this goes through the normal
connector/ingestion pipeline (chunked, embedded, queryable, cited) instead
of being globe-only telemetry.

Public domain US government data — https://www.usgs.gov/data.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

QUERY_API = "https://earthquake.usgs.gov/fdsnws/event/1/query"
LICENSE = "us-gov-open-data"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("usgs_earthquakes")
class UsgsEarthquakesConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._user_agent = self.config.get(
            "user_agent", "wardline-research-bot/0.1 (+mailto:contact@example.com)"
        )

    @_retry
    async def _get(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp

    async def discover(
        self,
        min_magnitude: float = 4.0,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 50,
    ) -> AsyncIterator[SourceItem]:
        params = {
            "format": "geojson",
            "orderby": "time",
            "minmagnitude": str(min_magnitude),
            "limit": str(limit),
        }
        if start_time:
            params["starttime"] = start_time
        if end_time:
            params["endtime"] = end_time
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            resp = await self._get(client, QUERY_API, params=params)
            for feature in resp.json().get("features", []):
                properties = feature["properties"]
                detail_url = properties.get("detail")
                if not detail_url:
                    continue  # no per-event detail endpoint to fetch -- skip rather than guess
                yield SourceItem(
                    ref=feature["id"],
                    hint_title=properties.get("place"),
                    extra={"detail_url": detail_url},
                )

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}) as client:
            resp = await self._get(client, item.extra["detail_url"])
            return RawObject(
                uri=item.extra["detail_url"],
                content=resp.content,
                content_type="application/json",
                fetched_at=datetime.now(UTC),
                extra={"usgs_id": item.ref},
            )

    def parse(self, raw: RawObject) -> ParsedDocument:
        data = json.loads(raw.content)
        properties = data["properties"]
        longitude, latitude, depth_km = data["geometry"]["coordinates"]
        magnitude = properties["mag"]
        place = properties["place"] or "an unspecified location"
        occurred_at = datetime.fromtimestamp(properties["time"] / 1000, tz=UTC)

        sentence = (
            f"A magnitude {magnitude} earthquake occurred {place} at "
            f"{occurred_at.isoformat()}, at a depth of {depth_km:.1f} km "
            f"(USGS event {raw.extra['usgs_id']})."
        )
        if properties.get("tsunami") == 1:
            sentence += " USGS flagged this event with tsunami potential."

        return ParsedDocument(
            uri=raw.uri,
            title=f"M{magnitude} earthquake — {place}",
            text=sentence,
            lang="en",
            published_at=occurred_at,
            extra={
                "usgs_id": raw.extra["usgs_id"],
                "magnitude": magnitude,
                "place": place,
                "latitude": latitude,
                "longitude": longitude,
                "depth_km": depth_km,
            },
        )
