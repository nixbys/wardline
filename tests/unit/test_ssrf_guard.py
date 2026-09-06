"""Unit coverage for common/ssrf_guard.py.

Disallowed cases use numeric IP-literal hostnames (127.0.0.1, 169.254.x.x,
...) — these resolve without any real DNS lookup (handled locally by libc),
so these tests don't depend on network access. The one "safe" case mocks
`getaddrinfo` to return a real public IP, for the same reason: no test in
this suite should depend on live DNS/network to pass.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wardline.common.ssrf_guard import UnsafeUrlError, assert_safe_url


async def test_rejects_disallowed_scheme():
    with pytest.raises(UnsafeUrlError, match="scheme"):
        await assert_safe_url("ftp://example.com/file")


async def test_rejects_url_with_no_host():
    with pytest.raises(UnsafeUrlError, match="no host"):
        await assert_safe_url("http:///path")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://[fe80::1]/",
    ],
)
async def test_rejects_private_and_internal_ip_literals(url):
    with pytest.raises(UnsafeUrlError, match="disallowed address"):
        await assert_safe_url(url)


async def test_rejects_unresolvable_host():
    with pytest.raises(UnsafeUrlError, match="could not resolve"):
        await assert_safe_url("http://this-host-does-not-exist.invalid/")


async def test_allows_a_public_address():
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = mock_get_loop.return_value
        mock_loop.getaddrinfo = AsyncMock(return_value=[(2, 1, 6, "", ("8.8.8.8", 0))])
        await assert_safe_url("https://example.com/")  # does not raise
