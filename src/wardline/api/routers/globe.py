"""Live Globe (`globe/`, the CesiumJS frontend) proxy API.

Everything in `web/`'s other routers guards *documents*: fetched once,
chunked, embedded, cited. The globe's feeds are the opposite shape —
continuously-updating positions (aircraft, vessels, satellites, traffic)
that are never "a source" a RAG answer could cite, only a live picture of
right now. Forcing them through `connectors/` + the ingestion pipeline
would misrepresent what "citable" means in this codebase, so they stay
here instead: thin, cached, unauthenticated passthroughs to each public
API, using Wardline's own stored keys so a viewer of the globe page never
needs (or sees) one. Contrast with `connectors/usgs_earthquakes.py` and
`connectors/nasa_firms.py`, which *are* discrete citable events and do go
through the normal connector pipeline.

Deliberately public (no `get_current_user`, no RBAC/engagement check):
this isn't a target-lookup connector like `shodan`/`nmap` — it's read-only
public telemetry, the same trust tier as `index.html`/`pricing.html`. It
still goes through the same `slowapi` limiter as everything else, because
"public and unauthenticated" plus "proxies a rate/cost-limited third-party
API" is exactly the combination that needs a cap — otherwise many browser
tabs polling this endpoint turn into an unbounded amplifier against
AISStream's/TomTom's own quota.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.governance.rate_limit import limiter

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/globe", tags=["globe"])

OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"
OPENAI_REALTIME_SESSIONS_URL = "https://api.openai.com/v1/realtime/sessions"

# Small allowlist, not a free-text passthrough -- `group` reaches CelesTrak's
# own URL verbatim, so an open passthrough would turn this endpoint into a
# generic SSRF-flavored proxy for any celestrak.org query string.
_CELESTRAK_GROUPS = {"stations", "visual", "active", "weather", "gps-ops"}

# name -> (settings attrs that must be non-empty for this layer to be "on")
_LAYER_REQUIRES: dict[str, tuple[str, ...]] = {
    "opensky": (),  # anonymous access works; client_id/secret just raises the quota
    "celestrak": (),
    "aisstream": ("aisstream_api_key",),
    "traffic": ("tomtom_api_key",),
    "voice": ("openai_api_key",),
}

# In-memory cache: cache_key -> (fetched_at_monotonic, payload). Deliberately
# process-local, not shared/Redis-backed -- a `globe_proxy_cache_seconds`
# staleness window this short doesn't need cross-worker coherence, only to
# stop each worker individually from hammering upstream.
_cache: dict[str, tuple[float, object]] = {}


async def _cached(key: str, fetch) -> object:
    settings = get_settings()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and (now - hit[0]) < settings.globe_proxy_cache_seconds:
        return hit[1]
    value = await fetch()
    _cache[key] = (now, value)
    return value


def _layer_enabled(name: str) -> bool:
    settings = get_settings()
    return all(getattr(settings, attr, None) for attr in _LAYER_REQUIRES[name])


@router.get("/config")
def globe_config() -> dict:
    """What the frontend renders its layer toggles from -- never a
    hard-coded copy in `globe/`, same principle as `GET /v1/billing/plans`
    for the pricing page."""
    return {"layers": {name: _layer_enabled(name) for name in _LAYER_REQUIRES}}


async def _opensky_token(settings) -> str | None:
    if not (settings.opensky_client_id and settings.opensky_client_secret):
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            OPENSKY_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.opensky_client_id,
                "client_secret": settings.opensky_client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


@router.get("/opensky")
@limiter.limit(f"{get_settings().rate_limit_globe_per_minute}/minute")
async def opensky_states(
    request: Request,
    lamin: float | None = Query(default=None),
    lomin: float | None = Query(default=None),
    lamax: float | None = Query(default=None),
    lomax: float | None = Query(default=None),
) -> dict:
    """Live aircraft state vectors, optionally bounded to a viewport bbox
    (all four params or none -- OpenSky rejects a partial box itself)."""
    settings = get_settings()
    bbox = (lamin, lomin, lamax, lomax)
    cache_key = f"opensky:{bbox}"

    async def fetch() -> dict:
        params = {}
        if all(v is not None for v in bbox):
            params = {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}
        headers = {}
        token = await _opensky_token(settings)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPENSKY_STATES_URL, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    try:
        return await _cached(cache_key, fetch)
    except httpx.HTTPError as exc:
        logger.error("globe.opensky_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="opensky upstream unavailable") from exc


@router.get("/celestrak")
@limiter.limit(f"{get_settings().rate_limit_globe_per_minute}/minute")
async def celestrak_gp(
    request: Request, group: str = Query(default="stations"), format: str = Query(default="json")
):
    """`format=json` is a plain snapshot (no velocity, fine for a label
    list); `format=tle` returns the raw two-line-element text the frontend
    feeds to `satellite.js` for real SGP4 position propagation -- CelesTrak
    has no JSON shape that carries the orbital elements SGP4 needs, only
    the classic TLE/OMM text formats."""
    if group not in _CELESTRAK_GROUPS:
        raise HTTPException(status_code=400, detail=f"group must be one of {sorted(_CELESTRAK_GROUPS)}")
    if format not in ("json", "tle"):
        raise HTTPException(status_code=400, detail="format must be 'json' or 'tle'")
    cache_key = f"celestrak:{group}:{format}"

    async def fetch():
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(CELESTRAK_URL, params={"GROUP": group, "FORMAT": format})
            resp.raise_for_status()
            return resp.json() if format == "json" else resp.text

    try:
        result = await _cached(cache_key, fetch)
    except httpx.HTTPError as exc:
        logger.error("globe.celestrak_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="celestrak upstream unavailable") from exc
    return PlainTextResponse(result) if format == "tle" else result


@router.get("/traffic")
@limiter.limit(f"{get_settings().rate_limit_globe_per_minute}/minute")
async def traffic_flow(request: Request, lat: float = Query(...), lon: float = Query(...)) -> dict:
    settings = get_settings()
    if not settings.tomtom_api_key:
        raise HTTPException(status_code=503, detail="traffic layer not configured (TOMTOM_API_KEY unset)")
    cache_key = f"traffic:{lat}:{lon}"

    async def fetch() -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                TOMTOM_FLOW_URL,
                params={"point": f"{lat},{lon}", "key": settings.tomtom_api_key},
            )
            resp.raise_for_status()
            return resp.json()

    try:
        return await _cached(cache_key, fetch)
    except httpx.HTTPError as exc:
        logger.error("globe.traffic_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="tomtom upstream unavailable") from exc


async def _collect_aisstream(api_key: str, bbox: list[list[float]], seconds: float) -> dict:
    """AISStream has no REST equivalent -- only a WebSocket subscription
    protocol. Rather than keep a persistent connection alive for the life of
    the process (a real background-task/reconnect-logic surface this
    milestone doesn't need yet), open one short-lived connection per
    cache-miss, collect whatever position reports arrive in `seconds`, and
    close it. `globe_proxy_cache_seconds` bounds how often that happens.
    """
    import websockets

    vessels: dict[str, dict] = {}
    deadline = time.monotonic() + seconds
    async with websockets.connect(AISSTREAM_WS_URL, open_timeout=10) as ws:
        await ws.send(
            json.dumps(
                {
                    "APIKey": api_key,
                    "BoundingBoxes": [bbox],
                    "FilterMessageTypes": ["PositionReport"],
                }
            )
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), remaining)
            except TimeoutError:
                break
            try:
                message = json.loads(raw)
                report = message["Message"]["PositionReport"]
                mmsi = str(report["UserID"])
                vessels[mmsi] = {
                    "mmsi": mmsi,
                    "lat": report["Latitude"],
                    "lon": report["Longitude"],
                    "course": report.get("Cog"),
                    "speed": report.get("Sog"),
                    "received_at": datetime.now(UTC).isoformat(),
                }
            except (KeyError, ValueError, TypeError):
                continue  # not a position report we render -- skip, don't fail the whole batch
    return {"vessels": list(vessels.values())}


@router.get("/aisstream")
@limiter.limit(f"{get_settings().rate_limit_globe_per_minute}/minute")
async def aisstream_vessels(
    request: Request,
    lamin: float = Query(...),
    lomin: float = Query(...),
    lamax: float = Query(...),
    lomax: float = Query(...),
) -> dict:
    settings = get_settings()
    if not settings.aisstream_api_key:
        raise HTTPException(status_code=503, detail="ship layer not configured (AISSTREAM_API_KEY unset)")
    bbox = [[lamin, lomin], [lamax, lomax]]
    cache_key = f"aisstream:{bbox}"

    async def fetch() -> dict:
        return await _collect_aisstream(settings.aisstream_api_key, bbox, seconds=2.0)

    try:
        return await _cached(cache_key, fetch)
    except OSError as exc:
        logger.error("globe.aisstream_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="aisstream upstream unavailable") from exc


@router.post("/realtime-session")
@limiter.limit(f"{get_settings().rate_limit_globe_per_minute}/minute")
async def realtime_session(request: Request) -> dict:
    """Mints a short-lived OpenAI Realtime ephemeral token server-side for
    the globe's voice-control feature. The browser only ever receives this
    token, never `settings.openai_api_key` itself -- the same
    server-side-proxy role the upstream project's own Node proxy plays."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="voice control not configured (OPENAI_API_KEY unset)")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                OPENAI_REALTIME_SESSIONS_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "gpt-realtime", "voice": "verse"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("globe.realtime_session_failed", error=str(exc))
            raise HTTPException(status_code=502, detail="openai realtime upstream unavailable") from exc
    return resp.json()
