"""Unit coverage for connectors/spiderfoot.py. Uses respx to mock its HTTP
calls, same convention as test_web_crawler.py -- no real network access.
The engagement-gating primitive itself (requires_engagement,
enforce_engagement_scope) is covered in test_engagements.py/test_rbac_abac.py
and test_dual_use_connectors.py's shared assertions; this file covers what's
specific to this connector: the start/poll/retrieve lifecycle, the
timeout-then-stop-scan path, and parse()'s rendering of one correlated
finding into a citable document.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from wardline.connectors.base import RawObject
from wardline.connectors.spiderfoot import SpiderFootConnector
from wardline.ingestion.quality_gates import KNOWN_LICENSES

BASE_URL = "http://spiderfoot.test:5001"


def _connector(**overrides) -> SpiderFootConnector:
    config = {"base_url": BASE_URL, "poll_interval_seconds": 0, "max_wait_seconds": 5, **overrides}
    return SpiderFootConnector(config=config)


def test_carries_known_internal_license_and_requires_engagement():
    assert SpiderFootConnector.default_license == "internal-only"
    assert SpiderFootConnector.default_license in KNOWN_LICENSES
    assert SpiderFootConnector.requires_engagement is True


async def test_discover_raises_without_a_configured_base_url():
    connector = SpiderFootConnector(config={})
    with pytest.raises(RuntimeError, match="SPIDERFOOT_URL"):
        async for _ in connector.discover(target="example.com"):
            pass


async def test_discover_rejects_an_unknown_use_case():
    connector = _connector()
    with pytest.raises(ValueError, match="use_case must be one of"):
        async for _ in connector.discover(target="example.com", use_case="bogus"):
            pass


@respx.mock
async def test_discover_runs_the_full_lifecycle_and_skips_root_events():
    respx.post(f"{BASE_URL}/startscan").mock(
        return_value=httpx.Response(200, json=["SUCCESS", "scan123"])
    )
    respx.get(f"{BASE_URL}/scanstatus", params={"id": "scan123"}).mock(
        side_effect=[
            httpx.Response(200, json=["n", "example.com", "c", "s", "e", "RUNNING", {}]),
            httpx.Response(200, json=["n", "example.com", "c", "s", "e", "FINISHED", {}]),
        ]
    )
    respx.get(f"{BASE_URL}/scanexportjsonmulti", params={"ids": "scan123"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"event_type": "ROOT", "data": "example.com", "module": "", "source_data": ""},
                {
                    "event_type": "EMAILADDR",
                    "data": "person@example.com",
                    "module": "sfp_hunter",
                    "source_data": "example.com",
                    "false_positive": 0,
                },
            ],
        )
    )

    connector = _connector()
    items = [item async for item in connector.discover(target="example.com")]

    assert len(items) == 1  # ROOT filtered out
    item = items[0]
    assert item.hint_title == "EMAILADDR"
    assert item.extra["target"] == "example.com"
    assert item.extra["scan_id"] == "scan123"
    assert item.extra["finding"]["data"] == "person@example.com"


@respx.mock
async def test_discover_stops_the_scan_once_max_wait_is_exceeded():
    respx.post(f"{BASE_URL}/startscan").mock(
        return_value=httpx.Response(200, json=["SUCCESS", "scan999"])
    )
    # Never reaches a terminal state on its own -- exercises the timeout path.
    respx.get(f"{BASE_URL}/scanstatus", params={"id": "scan999"}).mock(
        return_value=httpx.Response(200, json=["n", "t", "c", "s", "e", "RUNNING", {}])
    )
    stop_route = respx.get(f"{BASE_URL}/stopscan", params={"id": "scan999"}).mock(
        return_value=httpx.Response(200, text="")
    )
    respx.get(f"{BASE_URL}/scanexportjsonmulti", params={"ids": "scan999"}).mock(
        return_value=httpx.Response(200, json=[])
    )

    connector = _connector(max_wait_seconds=0, poll_interval_seconds=0)
    items = [item async for item in connector.discover(target="example.com")]

    assert items == []
    assert stop_route.called


@respx.mock
async def test_discover_raises_when_spiderfoot_rejects_the_scan():
    respx.post(f"{BASE_URL}/startscan").mock(
        return_value=httpx.Response(200, json=["ERROR", "Unrecognised target type."])
    )
    connector = _connector()
    with pytest.raises(RuntimeError, match="Unrecognised target type"):
        async for _ in connector.discover(target="not a valid target"):
            pass


def test_parse_renders_a_citable_sentence_with_source_and_module():
    finding = {
        "event_type": "EMAILADDR",
        "data": "person@example.com",
        "module": "sfp_hunter",
        "source_data": "example.com",
        "false_positive": 0,
    }
    raw = RawObject(
        uri="spiderfoot://scan123/scan123:abc",
        content=json.dumps(finding).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"target": "example.com", "scan_id": "scan123"},
    )
    doc = SpiderFootConnector().parse(raw)
    assert doc.title == "SpiderFoot: EMAILADDR — example.com"
    assert "sfp_hunter module found EMAILADDR for example.com: person@example.com" in doc.text
    assert "Source: example.com." in doc.text
    assert "false positive" not in doc.text
    assert doc.extra["false_positive"] is False


def test_parse_flags_a_false_positive():
    finding = {
        "event_type": "IP_ADDRESS",
        "data": "203.0.113.7",
        "module": "sfp_dnsresolve",
        "source_data": "203.0.113.7",
        "false_positive": 1,
    }
    raw = RawObject(
        uri="spiderfoot://scan123/scan123:def",
        content=json.dumps(finding).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"target": "example.com", "scan_id": "scan123"},
    )
    doc = SpiderFootConnector().parse(raw)
    assert "Flagged as a likely false positive." in doc.text
    assert doc.extra["false_positive"] is True


async def test_fetch_repackages_from_extra_with_no_network_call():
    connector = SpiderFootConnector()
    from wardline.connectors.base import SourceItem

    item = SourceItem(
        ref="scan123:abc",
        extra={
            "finding": {"event_type": "EMAILADDR", "data": "x@example.com"},
            "target": "example.com",
            "scan_id": "scan123",
        },
    )
    raw = await connector.fetch(item)
    assert json.loads(raw.content)["data"] == "x@example.com"
    assert raw.extra["scan_id"] == "scan123"
