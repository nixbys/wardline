"""Unit coverage for api/routers/globe.py's non-network logic: which layers
`GET /v1/globe/config` reports as enabled, driven purely by which optional
settings are configured. The actual proxy calls (opensky/celestrak/traffic/
aisstream/realtime-session) all make real outbound network calls and are
exercised manually/in integration, not here -- same split this repo already
uses for other outbound-network connectors (see test_dual_use_connectors.py's
docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.api.routers import globe
from wardline.common.config import Settings, get_settings
from wardline.storage.models.base import Base
from wardline.storage.models.documents import Document


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


# --- GET /v1/globe/history -----------------------------------------------


@pytest.fixture()
def documents_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Document.__table__])
    with Session(engine) as session:
        yield session


def _doc(connector: str, lat: float, lon: float, published_at: datetime, status: str = "active") -> Document:
    return Document(
        uri=f"{connector}://{lat}/{lon}",
        title="t",
        published_at=published_at,
        license="us-gov-open-data",
        content_hash="x" * 64,
        source_connector=connector,
        status=status,
        extra={"latitude": lat, "longitude": lon},
    )


def test_history_rejects_a_connector_outside_the_allowlist():
    with pytest.raises(HTTPException) as exc_info:
        globe.globe_history.__wrapped__(
            request=None,
            connector="spiderfoot",  # internal-only -- must never be readable through this public route
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2021, 1, 1, tzinfo=UTC),
            limit=500,
            db=None,
        )
    assert exc_info.value.status_code == 400


def test_history_rejects_end_before_start():
    with pytest.raises(HTTPException) as exc_info:
        globe.globe_history.__wrapped__(
            request=None,
            connector="usgs_earthquakes",
            start=datetime(2021, 1, 1, tzinfo=UTC),
            end=datetime(2020, 1, 1, tzinfo=UTC),
            limit=500,
            db=None,
        )
    assert exc_info.value.status_code == 400


def test_history_returns_only_the_requested_connector_and_range(documents_db):
    db = documents_db
    db.add_all(
        [
            _doc("usgs_earthquakes", 1.0, 2.0, datetime(2020, 6, 1, tzinfo=UTC)),
            _doc("usgs_earthquakes", 3.0, 4.0, datetime(2023, 6, 1, tzinfo=UTC)),  # outside range
            _doc("nasa_firms", 5.0, 6.0, datetime(2020, 6, 1, tzinfo=UTC)),  # wrong connector
            _doc("usgs_earthquakes", 7.0, 8.0, datetime(2020, 7, 1, tzinfo=UTC), status="quarantined"),
        ]
    )
    db.flush()

    results = globe.globe_history.__wrapped__(
        request=None,
        connector="usgs_earthquakes",
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2021, 1, 1, tzinfo=UTC),
        limit=500,
        db=db,
    )

    assert len(results) == 1
    assert results[0]["latitude"] == 1.0
    assert results[0]["longitude"] == 2.0


def test_history_end_is_exclusive(documents_db):
    db = documents_db
    boundary = datetime(2021, 1, 1, tzinfo=UTC)
    db.add(_doc("usgs_earthquakes", 1.0, 2.0, boundary))
    db.flush()

    results = globe.globe_history.__wrapped__(
        request=None,
        connector="usgs_earthquakes",
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=boundary,
        limit=500,
        db=db,
    )
    assert results == []
