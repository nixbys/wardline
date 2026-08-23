"""Per-API-key rate limiting (report 4.7 anti-exfiltration control)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _key_func(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :]
    return get_remote_address(request)


limiter = Limiter(key_func=_key_func)
