"""SpiderFoot connector — correlated OSINT automation, the dual-use
category's third member alongside `threat_intel.py` (Shodan, one passive
lookup) and `nmap_scan.py` (one active scan). Where those two each do one
narrow thing, SpiderFoot runs 200+ modules (DNS, breach/leak databases,
threat intel, social, cloud assets, and more) against one target and
correlates the results — most modules are passive, a handful are
active-adjacent (subdomain brute-forcing, an optional nmap sub-scan), which
is why this is dual-use and engagement-gated like its siblings, not a
public-corpus connector.

This doesn't vendor or depend on SpiderFoot's *code* — it's an independent,
MIT-licensed application (github.com/smicallef/spiderfoot) called over a
network boundary, same posture this project already takes with Shodan's
API. `SPIDERFOOT_URL` is a plain external dependency: it can point at a
sidecar this deployment starts itself, or at an *already-running* instance
another cooperating deployment owns (per internal planning notes' "avoid
duplicate infrastructure" principle) — this connector doesn't know or
care which, and doesn't stand one up implicitly.

SpiderFoot's own web API has no bulk/streaming result endpoint — it's a
start → poll → retrieve lifecycle (scans run minutes to tens of minutes):
  POST /startscan   -> {"SUCCESS", scan_id} | {"ERROR", message}
  GET  /scanstatus?id=<id>          -> [name, target, created, started, ended, status, riskmatrix]
  GET  /scanexportjsonmulti?ids=<id> -> [{data, event_type, module, source_data, ...}, ...]
`discover()` runs that whole lifecycle (bounded by `max_wait_seconds` —
a scan that's still running when the bound hits is stopped and whatever it
already found is still used, not discarded) and yields one `SourceItem`
per correlated finding, each carrying its own already-fetched event data —
there's no per-finding detail endpoint to re-fetch from, the same "discover
already has the bytes" shape `connectors/nasa_firms.py` uses.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.common.logging import get_logger
from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

LICENSE = "internal-only"

# Matches sf.py's own `-u` argparse choices -- an allowlist, not a
# passthrough, so a typo doesn't silently reach SpiderFoot as some other
# unintended query.
USE_CASES = {"all", "footprint", "investigate", "passive"}

# Scan-state terminal values (sfscan.py's own __setStatus() calls). Anything
# else (INITIALIZING, STARTING, RUNNING) means "keep polling."
_TERMINAL_STATUSES = {"FINISHED", "ABORTED", "ERROR-FAILED"}

logger = get_logger(__name__)

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("spiderfoot")
class SpiderFootConnector(Connector):
    default_license = LICENSE
    requires_engagement = True

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._base_url = (self.config.get("base_url") or "").rstrip("/")
        username = self.config.get("username")
        self._auth = (username, self.config.get("password") or "") if username else None
        self._default_use_case = self.config.get("use_case", "footprint")
        self._max_wait_seconds = self.config.get("max_wait_seconds", 1800)
        self._poll_interval_seconds = self.config.get("poll_interval_seconds", 15)

    @_retry
    async def _start_scan(self, client: httpx.AsyncClient, target: str, use_case: str) -> str:
        resp = await client.post(
            f"{self._base_url}/startscan",
            data={"scanname": f"wardline: {target}", "scantarget": target, "modulelist": "", "typelist": "", "usecase": use_case},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        status, payload = resp.json()
        if status != "SUCCESS":
            raise RuntimeError(f"SpiderFoot rejected the scan request: {payload}")
        return payload  # the scan id

    @_retry
    async def _scan_status(self, client: httpx.AsyncClient, scan_id: str) -> str:
        resp = await client.get(f"{self._base_url}/scanstatus", params={"id": scan_id})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise RuntimeError(f"SpiderFoot has no record of scan {scan_id!r}")
        return data[5]

    async def _wait_until_done(self, client: httpx.AsyncClient, scan_id: str) -> None:
        deadline = time.monotonic() + self._max_wait_seconds
        while True:
            status = await self._scan_status(client, scan_id)
            if status in _TERMINAL_STATUSES:
                if status != "FINISHED":
                    logger.error("spiderfoot.scan_ended_abnormally", scan_id=scan_id, status=status)
                return
            if time.monotonic() >= deadline:
                logger.error("spiderfoot.scan_timed_out", scan_id=scan_id, max_wait_seconds=self._max_wait_seconds)
                await self._stop_scan(client, scan_id)
                return
            await asyncio.sleep(self._poll_interval_seconds)

    async def _stop_scan(self, client: httpx.AsyncClient, scan_id: str) -> None:
        # Best-effort -- whatever the scan already found is still usable below.
        with contextlib.suppress(httpx.HTTPError):
            await client.get(f"{self._base_url}/stopscan", params={"id": scan_id})

    @_retry
    async def _get_results(self, client: httpx.AsyncClient, scan_id: str) -> list[dict]:
        resp = await client.get(f"{self._base_url}/scanexportjsonmulti", params={"ids": scan_id})
        resp.raise_for_status()
        return resp.json()

    async def discover(
        self,
        target: str,
        engagement_id: str | None = None,
        use_case: str | None = None,
        **kwargs,
    ) -> AsyncIterator[SourceItem]:
        if not self._base_url:
            raise RuntimeError("SPIDERFOOT_URL is not configured")
        resolved_use_case = use_case or self._default_use_case
        if resolved_use_case not in USE_CASES:
            raise ValueError(f"use_case must be one of {sorted(USE_CASES)}")

        async with httpx.AsyncClient(auth=self._auth, timeout=30) as client:
            scan_id = await self._start_scan(client, target, resolved_use_case)
            await self._wait_until_done(client, scan_id)
            findings = await self._get_results(client, scan_id)

        for finding in findings:
            if finding.get("event_type") == "ROOT":
                continue  # SpiderFoot's own synthetic root node for the target itself -- not a finding
            # SpiderFoot already dedupes internally; this hash just gives
            # each finding a stable, unique SourceItem.ref for this scan.
            digest = hashlib.sha256(
                f"{finding.get('event_type')}:{finding.get('module')}:{finding.get('data')}".encode()
            ).hexdigest()[:16]
            yield SourceItem(
                ref=f"{scan_id}:{digest}",
                hint_title=finding.get("event_type"),
                extra={"finding": finding, "target": target, "scan_id": scan_id},
            )

    async def fetch(self, item: SourceItem) -> RawObject:
        return RawObject(
            uri=f"spiderfoot://{item.extra['scan_id']}/{item.ref}",
            content=json.dumps(item.extra["finding"]).encode("utf-8"),
            content_type="application/json",
            fetched_at=datetime.now(UTC),
            extra={"target": item.extra["target"], "scan_id": item.extra["scan_id"]},
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        finding = json.loads(raw.content)
        target = raw.extra["target"]
        event_type = finding.get("event_type", "UNKNOWN")
        module = finding.get("module", "unknown module")
        data = finding.get("data", "")
        source_data = finding.get("source_data", "")

        text = f"SpiderFoot's {module} module found {event_type} for {target}: {data}."
        if source_data and source_data != data:
            text += f" Source: {source_data}."
        if finding.get("false_positive"):
            text += " Flagged as a likely false positive."

        return ParsedDocument(
            uri=raw.uri,
            title=f"SpiderFoot: {event_type} — {target}",
            text=text,
            extra={
                "scan_id": raw.extra["scan_id"],
                "scan_target": target,
                "event_type": event_type,
                "module": module,
                "false_positive": bool(finding.get("false_positive")),
            },
        )
