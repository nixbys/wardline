"""Resolve each connector's runtime config from Settings.

Previously `get_connector(name)` was always called with no config anywhere
(worker/jobs.py, admin_connectors.py), so settings like
`sec_edgar_user_agent`/`crawler_user_agent` were dead: defined, documented in
.env.example, but never actually reaching a connector instance. That's a
latent bug on its own, and a hard blocker for `opencorporates`, which cannot
function at all without `opencorporates_api_token` reaching it.
"""

from __future__ import annotations

from wardline.common.config import get_settings


def resolve_connector_config(name: str) -> dict:
    settings = get_settings()

    if name == "sec_edgar":
        return {"user_agent": settings.sec_edgar_user_agent}
    if name == "web_crawler":
        return {
            "user_agent": settings.crawler_user_agent,
            "per_domain_delay_seconds": settings.crawler_per_domain_delay_seconds,
        }
    if name == "opencorporates":
        return {
            "user_agent": settings.crawler_user_agent,
            "api_token": settings.opencorporates_api_token,
        }
    if name in ("wikipedia", "archive_org", "wikidata", "usgs_earthquakes"):
        return {"user_agent": settings.crawler_user_agent}
    if name == "nasa_firms":
        return {"map_key": settings.nasa_firms_map_key}
    if name == "spiderfoot":
        return {
            "base_url": settings.spiderfoot_url,
            "username": settings.spiderfoot_username,
            "password": settings.spiderfoot_password,
            "use_case": settings.spiderfoot_use_case,
            "max_wait_seconds": settings.spiderfoot_max_wait_seconds,
            "poll_interval_seconds": settings.spiderfoot_poll_interval_seconds,
        }
    return {}
