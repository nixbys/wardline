"""Guards against server-side request forgery for any connector that fetches
a URL an authenticated caller supplies (currently `connectors/web_crawler.py`
-- `archive_org.py`'s outbound requests always target `web.archive.org`
itself, with the caller-supplied URL only ever landing in the *path*, not
the host, so it isn't in scope for this check).

Without this, an `analyst`-role caller (not just `admin` -- `web_crawler`
carries `requires_engagement = False`, unlike the dual-use connectors in
`nmap_scan.py`/`threat_intel.py`) could point `seeds` at a cloud metadata
endpoint (`169.254.169.254`) or an internal-only compose service
(`minio`/`neo4j`/`opensearch`) reachable from the worker container, and have
the response ingested and later readable back out through the ordinary
query/retrieval path.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("http", "https")


class UnsafeUrlError(ValueError):
    """Raised when a URL fails the SSRF safety check -- disallowed scheme,
    unresolvable host, or a host that resolves to a private/internal
    address."""


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def assert_safe_url(url: str) -> None:
    """Raises UnsafeUrlError unless `url` is http(s) and every address its
    host resolves to is a public, non-internal address. Call this again
    after following a redirect -- an initially-safe URL can redirect to an
    unsafe one, and re-validating the resolved *address* rather than trusting
    a scheme/hostname string is what actually closes that DNS-rebinding-style
    gap (a hostname can resolve differently between the check and the
    request, but re-checking on every hop, immediately before each request,
    is the practical mitigation available without a custom DNS-pinning
    transport).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"unsupported URL scheme in {url!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"no host in {url!r}")

    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host in {url!r}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_disallowed_ip(ip):
            raise UnsafeUrlError(f"{url!r} resolves to a disallowed address ({ip})")
