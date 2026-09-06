"""Unit coverage for connectors/web_crawler.py's SSRF guard integration
(common/ssrf_guard.py's own logic is covered directly in test_ssrf_guard.py).
Uses respx to mock httpx without any real network access.
"""

from __future__ import annotations

import asyncio
import ipaddress
from unittest.mock import patch

import httpx
import respx

from wardline.connectors.web_crawler import WebCrawlerConnector


async def _fake_getaddrinfo(host, *_args, **_kwargs):
    """Stands in for a real resolver without live DNS: a real (non-numeric)
    hostname like "example.com" resolves to a fixed public IP; a numeric IP
    literal resolves to itself, exactly like the real resolver would (no
    network needed for that case either way) -- this distinction matters
    because a redirect-to-an-IP-literal test needs that literal to still
    come back private, not get laundered into "safe" by a blanket mock."""
    try:
        ipaddress.ip_address(host)
        resolved = host
    except ValueError:
        resolved = "8.8.8.8"
    return [(2, 1, 6, "", (resolved, 0))]


def _patch_dns():
    """Patches asyncio.get_event_loop() so assert_safe_url's DNS resolution
    (called via `loop.getaddrinfo`) doesn't depend on live DNS. Preserves
    the real `.time()` method web_crawler.py's own politeness-delay logic
    also calls on the same loop object."""
    patcher = patch("asyncio.get_event_loop")
    mock_get_loop = patcher.start()
    mock_get_loop.return_value.getaddrinfo = _fake_getaddrinfo
    mock_get_loop.return_value.time = asyncio.get_event_loop().time
    return patcher


@respx.mock
async def test_discover_skips_a_seed_that_resolves_to_a_private_address():
    # 169.254.169.254 is a numeric IP literal -- assert_safe_url rejects it
    # without any DNS lookup, so no respx route for it is even needed; the
    # request must never be attempted.
    items = [
        item
        async for item in WebCrawlerConnector().discover(
            seeds=["http://169.254.169.254/latest/meta-data/"]
        )
    ]
    assert items == []


@respx.mock
async def test_discover_yields_a_page_from_a_safe_seed():
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")
    )

    patcher = _patch_dns()
    try:
        items = [
            item async for item in WebCrawlerConnector().discover(seeds=["https://example.com/"])
        ]
    finally:
        patcher.stop()

    assert len(items) == 1
    assert items[0].ref == "https://example.com/"


@respx.mock
async def test_discover_skips_a_redirect_to_a_private_address():
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )

    # Only the initial, safe hostname's resolution is mocked -- the redirect
    # target below is a numeric IP literal, so assert_safe_url rejects it
    # directly on the next hop regardless of what this mock returns.
    patcher = _patch_dns()
    try:
        items = [
            item async for item in WebCrawlerConnector().discover(seeds=["https://example.com/"])
        ]
    finally:
        patcher.stop()

    assert items == []
