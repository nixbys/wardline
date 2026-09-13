"""Unit coverage for the two discrete-event Live Globe connectors
(connectors/usgs_earthquakes.py, connectors/nasa_firms.py). Both follow the
"discover() finds refs, fetch() retrieves, parse() renders a citable
sentence" shape covered elsewhere for other connectors (test_dual_use_
connectors.py); this file covers what's specific to these two: the license
tag they carry, and that parse() turns real-shaped upstream payloads into a
sane declarative ParsedDocument without a live network call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from wardline.connectors.base import RawObject
from wardline.connectors.nasa_firms import NasaFirmsConnector
from wardline.connectors.usgs_earthquakes import UsgsEarthquakesConnector
from wardline.ingestion.quality_gates import KNOWN_LICENSES


def test_usgs_connector_carries_known_public_license():
    assert UsgsEarthquakesConnector.default_license == "us-gov-open-data"
    assert UsgsEarthquakesConnector.default_license in KNOWN_LICENSES
    assert UsgsEarthquakesConnector.requires_engagement is False


def test_firms_connector_carries_known_public_license():
    assert NasaFirmsConnector.default_license == "us-gov-open-data"
    assert NasaFirmsConnector.default_license in KNOWN_LICENSES
    assert NasaFirmsConnector.requires_engagement is False


def test_usgs_parse_renders_a_citable_sentence_with_coordinates():
    feature_detail = {
        "id": "us7000abcd",
        "properties": {"mag": 5.2, "place": "10km SE of Testville", "time": 1700000000000, "tsunami": 1},
        "geometry": {"coordinates": [-122.4, 37.7, 12.3]},
    }
    raw = RawObject(
        uri="https://earthquake.usgs.gov/.../us7000abcd.geojson",
        content=json.dumps(feature_detail).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"usgs_id": "us7000abcd"},
    )
    doc = UsgsEarthquakesConnector().parse(raw)
    assert doc.title == "M5.2 earthquake — 10km SE of Testville"
    assert "magnitude 5.2 earthquake" in doc.text
    assert "10km SE of Testville" in doc.text
    assert "us7000abcd" in doc.text
    assert "tsunami potential" in doc.text  # tsunami=1 appends the extra sentence
    assert doc.extra["latitude"] == 37.7
    assert doc.extra["longitude"] == -122.4
    assert doc.published_at == datetime.fromtimestamp(1700000000000 / 1000, tz=UTC)


def test_usgs_parse_omits_tsunami_sentence_when_not_flagged():
    feature_detail = {
        "id": "us7000wxyz",
        "properties": {"mag": 3.1, "place": "5km N of Elsewhere", "time": 1700000000000, "tsunami": 0},
        "geometry": {"coordinates": [10.0, 20.0, 5.0]},
    }
    raw = RawObject(
        uri="https://earthquake.usgs.gov/.../us7000wxyz.geojson",
        content=json.dumps(feature_detail).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"usgs_id": "us7000wxyz"},
    )
    doc = UsgsEarthquakesConnector().parse(raw)
    assert "tsunami" not in doc.text


def test_firms_parse_renders_a_citable_sentence_with_confidence_and_power():
    row = {
        "latitude": "37.7749",
        "longitude": "-122.4194",
        "acq_date": "2026-09-01",
        "acq_time": "930",
        "confidence": "nominal",
        "frp": "12.3",
        "satellite": "N",
    }
    raw = RawObject(
        uri="firms:37.7749:-122.4194:2026-09-01:930",
        content=json.dumps(row).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
    )
    doc = NasaFirmsConnector().parse(raw)
    assert doc.title == "Fire detection — 37.7749, -122.4194"
    assert "confidence: nominal" in doc.text
    assert "radiative power 12.3 MW" in doc.text
    assert doc.published_at == datetime(2026, 9, 1, 9, 30, tzinfo=UTC)


def test_firms_parse_handles_missing_radiative_power_gracefully():
    # Not every sensor/row reports frp -- must not KeyError or render "None MW".
    row = {
        "latitude": "1.0",
        "longitude": "2.0",
        "acq_date": "2026-09-01",
        "acq_time": "5",
        "confidence": "low",
    }
    raw = RawObject(
        uri="firms:1.0:2.0:2026-09-01:5",
        content=json.dumps(row).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
    )
    doc = NasaFirmsConnector().parse(raw)
    assert "radiative power" not in doc.text
    assert "confidence: low" in doc.text
    assert doc.published_at == datetime(2026, 9, 1, 0, 5, tzinfo=UTC)


async def test_firms_discover_requires_a_map_key():
    import pytest

    connector = NasaFirmsConnector(config={})
    with pytest.raises(ValueError, match="MAP_KEY"):
        async for _ in connector.discover():
            pass
