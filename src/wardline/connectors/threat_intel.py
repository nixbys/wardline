"""Shodan connector — dual-use exposure-search lookup, the category the
README and `connectors/base.py` docstring already named ("Shodan/Censys-
style exposure search") before any of it was actually integrated. Every run
is gated by `governance.pep.enforce_engagement_scope` before the job is even
queued (`api/routers/admin_connectors.py`): this connector never looks up a
target the caller doesn't hold an active, matching `Engagement` for. A role
(admin/analyst) only says who you are, not what you've been authorized to
look at — that's what the engagement asserts.

Findings are tagged `internal-only` (`governance/abac.py`) rather than the
public-corpus license tags every other connector uses — exposure data about
a specific target is a materially different sensitivity class, visible to
admin/analyst but not `viewer`.

Shodan's own Terms of Service govern redistribution/resale of data their API
returns — read those before this connector's output feeds anything a paying
customer sees, not just before ingesting it for internal research. This
connector only performs the lookup; it makes no claim about downstream
redistribution rights.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.common.config import get_settings
from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

API_BASE = "https://api.shodan.io"
LICENSE = "internal-only"

_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(4),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=20),
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
)


@register_connector("shodan")
class ShodanConnector(Connector):
    default_license = LICENSE
    requires_engagement = True

    async def discover(
        self, target: str, engagement_id: str | None = None, **kwargs
    ) -> AsyncIterator[SourceItem]:
        # `engagement_id` is accepted and ignored here on purpose: the admin
        # connector-run route always carries it into `job.params` once a
        # `requires_engagement=True` connector has cleared the PEP check, and
        # `run_connector_job` calls `discover(**params)` — a signature
        # without this would raise on every real invocation, not just look
        # unused.
        yield SourceItem(ref=target)

    @_retry
    async def _get_host(self, client: httpx.AsyncClient, ip: str) -> dict:
        api_key = get_settings().shodan_api_key
        if not api_key:
            raise RuntimeError("SHODAN_API_KEY is not configured")
        resp = await client.get(f"{API_BASE}/shodan/host/{ip}", params={"key": api_key}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient() as client:
            data = await self._get_host(client, item.ref)
        return RawObject(
            uri=f"shodan://{item.ref}",
            content=json.dumps(data).encode("utf-8"),
            content_type="application/json",
            fetched_at=datetime.now(UTC),
            extra={"target": item.ref},
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        data = json.loads(raw.content)
        ip = data.get("ip_str") or raw.extra.get("target", "unknown")
        org = data.get("org") or "an unknown organization"
        ports = [str(p) for p in data.get("ports", [])]
        hostnames = data.get("hostnames") or []

        lines = [
            f"Shodan exposure lookup for {ip}.",
            f"Registered to {org}.",
            f"Open ports observed: {', '.join(ports) if ports else 'none reported'}.",
            f"Known hostnames: {', '.join(hostnames) if hostnames else 'none reported'}.",
        ]
        for banner in data.get("data", []):
            product = banner.get("product")
            port = banner.get("port")
            if product and port:
                lines.append(f"Port {port} is running {product}.")

        return ParsedDocument(
            uri=f"shodan://{ip}",
            title=f"Shodan exposure report: {ip}",
            text="\n".join(lines),
            extra={"raw_shodan": data},
        )
