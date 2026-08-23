"""nmap connector — active network reconnaissance, the other half of the
dual-use category `connectors/base.py` names (alongside `threat_intel.py`'s
passive exposure lookups). Every run is gated by
`governance.pep.enforce_engagement_scope` before the job is even queued
(`api/routers/admin_connectors.py`): this connector never scans a target the
caller doesn't hold an active, matching `Engagement` for.
`governance.engagements.target_in_scope` understands CIDR ranges (not just
domain suffixes), since infrastructure engagements are routinely scoped to a
network block rather than one host.

The scan itself runs in the `toolrunner` sidecar (`docker/toolrunner/`),
never in this process. Two separate reasons, not one: nmap needs socket
access this API/worker container should never be granted, and keeping
execution in a small, single-purpose service limits blast radius if a target
or flag were ever manipulated upstream of the PEP check. This connector is a
thin HTTP client against that sidecar's allowlisted `/scan/nmap` endpoint —
it never constructs a shell command itself, and the sidecar re-validates the
target/ports shape independently rather than trusting this caller to have
already done it (defense in depth, not redundancy for its own sake).

Findings are tagged `internal-only` (`governance/abac.py`): raw scan output
is a materially different sensitivity class than the public-corpus documents
every other connector produces, visible to admin/analyst but not `viewer`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import tenacity

from wardline.common.config import get_settings
from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

LICENSE = "internal-only"

# Only two attempts, unlike the public-API connectors' four: a failed scan
# attempt has already spent real wall-clock time inside the sidecar's own
# timeout, and this project's Terms-of-Service-facing connectors (Wikidata,
# SEC EDGAR, ...) retry against a *rate limiter*, not against a target
# that's plausibly just not responding to a scan.
_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(2),
    wait=tenacity.wait_exponential(multiplier=2, min=2, max=10),
    retry=tenacity.retry_if_exception_type(httpx.TransportError),
)


@register_connector("nmap")
class NmapConnector(Connector):
    default_license = LICENSE
    requires_engagement = True

    async def discover(
        self,
        target: str,
        engagement_id: str | None = None,
        ports: str | None = None,
        **kwargs,
    ) -> AsyncIterator[SourceItem]:
        yield SourceItem(ref=target, extra={"ports": ports})

    @_retry
    async def _scan(self, client: httpx.AsyncClient, target: str, ports: str | None) -> str:
        settings = get_settings()
        if not settings.toolrunner_url:
            raise RuntimeError("TOOLRUNNER_URL is not configured")
        resp = await client.post(
            f"{settings.toolrunner_url}/scan/nmap",
            json={"target": target, "ports": ports},
            headers={"Authorization": f"Bearer {settings.toolrunner_token or ''}"},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.text

    async def fetch(self, item: SourceItem) -> RawObject:
        async with httpx.AsyncClient() as client:
            output = await self._scan(client, item.ref, item.extra.get("ports"))
        return RawObject(
            uri=f"nmap://{item.ref}",
            content=output.encode("utf-8"),
            content_type="text/plain",
            fetched_at=datetime.now(UTC),
            extra={"target": item.ref},
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        target = raw.extra.get("target", "unknown")
        return ParsedDocument(
            uri=f"nmap://{target}",
            title=f"nmap scan: {target}",
            text=raw.content.decode("utf-8", errors="replace"),
            extra={"scan_target": target},
        )
