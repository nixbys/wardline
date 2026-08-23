"""Minimal, single-purpose scan-execution sidecar.

Deliberately not part of the api/worker containers: nmap needs socket access
those containers should never be granted, and isolating execution here means
a bug (or a compromise) in the main app can't reach a capability that scans
a network just by being in the same process. This service re-validates every
input itself — it never trusts its caller (`wardline.connectors.nmap_scan`) to
have already checked shape, only to have already checked *authorization*
(that's `governance.pep.enforce_engagement_scope`'s job, upstream of this,
in the api container — this sidecar has no concept of engagements at all,
on purpose, so it can't become a second, inconsistent place that decision
gets made).

Not published on a host port in `docker-compose.yml` — reachable only from
other containers on the compose network, and in practice only ever called by
the `worker` container that actually runs ingestion jobs.

Scan behavior is deliberately conservative for a first cut: TCP connect
scan only (nmap's default without `-sS`), which doesn't need `NET_RAW`/
`NET_ADMIN` — so this container runs with no added capabilities and as a
non-root user (see Dockerfile). Extending this to more of Odysseus Red's
tool categories (sqlmap, nuclei, masscan, gobuster, nikto, theHarvester, ...)
means adding one more `/scan/<tool>` route each, following this exact
pattern: a strict input allowlist, a fixed non-shell argv, a timeout, and a
size-bounded response — not a generic "run any command" endpoint.
"""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

app = FastAPI(title="wardline-toolrunner")

_TOKEN = os.environ.get("TOOLRUNNER_TOKEN", "")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-.]{0,251}[a-zA-Z0-9])?$")
_PORTS_RE = re.compile(r"^[0-9,\-]{1,64}$")
_SCAN_TIMEOUT_SECONDS = 150
_MAX_OUTPUT_CHARS = 200_000


class ScanRequest(BaseModel):
    target: str
    ports: str | None = None


def _require_auth(authorization: str | None) -> None:
    if not _TOKEN:
        raise HTTPException(status_code=500, detail="TOOLRUNNER_TOKEN is not configured server-side")
    if authorization != f"Bearer {_TOKEN}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


def _validate_target(target: str) -> str:
    target = target.strip()
    try:
        # Covers bare IPs (as the implicit /32 or /128) and real CIDR
        # ranges with one check — see governance/engagements.py's
        # target_in_scope for why that's also how the *authorization*
        # check treats them.
        ipaddress.ip_network(target, strict=False)
        return target
    except ValueError:
        pass
    if _HOSTNAME_RE.match(target):
        return target
    raise HTTPException(status_code=400, detail=f"target {target!r} is not a valid host/IP/CIDR")


def _validate_ports(ports: str | None) -> str | None:
    if ports is None:
        return None
    if not _PORTS_RE.match(ports):
        raise HTTPException(
            status_code=400, detail="ports must look like '80,443' or '1-1024' — digits, commas, dashes only"
        )
    return ports


@app.post("/scan/nmap", response_class=PlainTextResponse)
def scan_nmap(body: ScanRequest, authorization: str | None = Header(default=None)) -> str:
    _require_auth(authorization)
    target = _validate_target(body.target)
    ports = _validate_ports(body.ports)

    # Fixed argv, never a shell string — `ports`/`target` land as discrete
    # list elements, not interpolated into anything a shell would re-parse.
    command = ["nmap", "-Pn", "-T4"]
    if ports:
        command += ["-p", ports]
    command += ["-oN", "-", target]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="scan timed out") from exc

    if result.returncode != 0:
        raise HTTPException(status_code=502, detail=(result.stderr or "nmap failed")[-2000:])

    return result.stdout[:_MAX_OUTPUT_CHARS]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
