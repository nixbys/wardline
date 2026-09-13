"""Unit coverage for api/routers/globe.py's non-network logic: which layers
`GET /v1/globe/config` reports as enabled, driven purely by which optional
settings are configured. The actual proxy calls (opensky/celestrak/traffic/
aisstream/realtime-session) all make real outbound network calls and are
exercised manually/in integration, not here -- same split this repo already
uses for other outbound-network connectors (see test_dual_use_connectors.py's
docstring).
"""

from __future__ import annotations

from wardline.api.routers import globe
from wardline.common.config import Settings, get_settings


def _settings_with(**overrides) -> Settings:
    base = get_settings()
    return Settings(**{**base.model_dump(), **overrides})


def test_config_reports_opensky_and_celestrak_enabled_with_no_keys_at_all(monkeypatch):
    monkeypatch.setattr(
        globe,
        "get_settings",
        lambda: _settings_with(
            aisstream_api_key=None, tomtom_api_key=None, openai_api_key=None
        ),
    )
    result = globe.globe_config()
    assert result["layers"]["opensky"] is True
    assert result["layers"]["celestrak"] is True
    assert result["layers"]["aisstream"] is False
    assert result["layers"]["traffic"] is False
    assert result["layers"]["voice"] is False


def test_config_reports_keyed_layers_enabled_once_configured(monkeypatch):
    monkeypatch.setattr(
        globe,
        "get_settings",
        lambda: _settings_with(
            aisstream_api_key="key", tomtom_api_key="key", openai_api_key="key"
        ),
    )
    result = globe.globe_config()
    assert result["layers"]["aisstream"] is True
    assert result["layers"]["traffic"] is True
    assert result["layers"]["voice"] is True


async def test_traffic_route_503s_without_a_configured_key(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(globe, "get_settings", lambda: _settings_with(tomtom_api_key=None))
    with pytest.raises(HTTPException) as exc_info:
        await globe.traffic_flow.__wrapped__(request=None, lat=1.0, lon=2.0)
    assert exc_info.value.status_code == 503


async def test_aisstream_route_503s_without_a_configured_key(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(globe, "get_settings", lambda: _settings_with(aisstream_api_key=None))
    with pytest.raises(HTTPException) as exc_info:
        await globe.aisstream_vessels.__wrapped__(
            request=None, lamin=1.0, lomin=1.0, lamax=2.0, lomax=2.0
        )
    assert exc_info.value.status_code == 503


async def test_realtime_session_503s_without_a_configured_key(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(globe, "get_settings", lambda: _settings_with(openai_api_key=None))
    with pytest.raises(HTTPException) as exc_info:
        await globe.realtime_session.__wrapped__(request=None)
    assert exc_info.value.status_code == 503
