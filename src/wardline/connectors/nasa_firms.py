"""NASA FIRMS (Fire Information for Resource Management System) connector —
discrete satellite fire detections, the discrete-event counterpart to
`api/routers/globe.py`'s live proxy layers. See `usgs_earthquakes.py`'s
module docstring for why this one goes through the normal citable-document
pipeline instead of staying globe-only telemetry.

FIRMS' area API returns a flat CSV of detections with no per-row detail
endpoint to re-fetch — `discover()` does the one network call and stashes
each row in `SourceItem.extra`, and `fetch()` repackages it with no further
network I/O, the same "already have the bytes" shape `connectors/upload.py`
uses.

Public domain US government data — https://www.earthdata.nasa.gov/data/tools/firms.
Requires a free MAP_KEY (https://firms.modaps.eosdis.nasa.gov/api/map_key/).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

AREA_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
LICENSE = "us-gov-open-data"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("nasa_firms")
class NasaFirmsConnector(Connector):
    default_license = LICENSE

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._map_key = self.config.get("map_key")

    @_retry
    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        return resp

    async def discover(
        self,
        area: str = "world",
        source: str = "VIIRS_SNPP_NRT",
        day_range: int = 1,
    ) -> AsyncIterator[SourceItem]:
        if not self._map_key:
            raise ValueError(
                "nasa_firms requires a MAP_KEY -- set NASA_FIRMS_MAP_KEY "
                "(free at https://firms.modaps.eosdis.nasa.gov/api/map_key/)"
            )
        url = f"{AREA_API_BASE}/{self._map_key}/{source}/{area}/{day_range}"
        async with httpx.AsyncClient() as client:
            resp = await self._get(client, url)
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                ref = f"firms:{row['latitude']}:{row['longitude']}:{row['acq_date']}:{row['acq_time']}"
                yield SourceItem(ref=ref, extra={"row": row})

    async def fetch(self, item: SourceItem) -> RawObject:
        return RawObject(
            uri=item.ref,
            content=json.dumps(item.extra["row"]).encode("utf-8"),
            content_type="application/json",
            fetched_at=datetime.now(UTC),
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        row = json.loads(raw.content)
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
        acq_time = row["acq_time"].zfill(4)  # "930" -> "0930"
        detected_at = datetime.strptime(
            f"{row['acq_date']} {acq_time}", "%Y-%m-%d %H%M"
        ).replace(tzinfo=UTC)
        confidence = row.get("confidence", "unknown")
        # VIIRS reports bright_ti4; MODIS reports brightness -- either may
        # be absent depending on `source`, so fall back gracefully rather
        # than KeyError on whichever one this row's sensor didn't report.
        frp = row.get("frp")

        sentence = (
            f"A satellite detected an active fire near {latitude:.4f}, {longitude:.4f} "
            f"at {detected_at.isoformat()} (confidence: {confidence}"
            + (f", radiative power {frp} MW" if frp else "")
            + ") — NASA FIRMS."
        )

        return ParsedDocument(
            uri=raw.uri,
            title=f"Fire detection — {latitude:.4f}, {longitude:.4f}",
            text=sentence,
            lang="en",
            published_at=detected_at,
            extra={
                "latitude": latitude,
                "longitude": longitude,
                "confidence": confidence,
                "frp_mw": frp,
                "satellite": row.get("satellite"),
            },
        )
