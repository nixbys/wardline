"""Unit coverage for the engagement-scoped connectors (connectors/nmap_scan.py,
connectors/threat_intel.py). The governance gate itself (requires_engagement,
enforce_engagement_scope) is covered in test_engagements.py and
test_rbac_abac.py — this file covers the two things specific to these
connectors: they carry `requires_engagement = True` and `default_license =
"internal-only"` (so a bug can't silently drop either), and their `parse()`
methods turn raw tool/API output into a sane `ParsedDocument` without needing
a live network call or a running toolrunner sidecar.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from wardline.connectors.base import RawObject
from wardline.connectors.nmap_scan import NmapConnector
from wardline.connectors.threat_intel import ShodanConnector


def test_nmap_connector_requires_engagement_and_internal_license():
    assert NmapConnector.requires_engagement is True
    assert NmapConnector.default_license == "internal-only"


def test_shodan_connector_requires_engagement_and_internal_license():
    assert ShodanConnector.requires_engagement is True
    assert ShodanConnector.default_license == "internal-only"


def test_nmap_parse_decodes_scan_output_and_titles_by_target():
    raw = RawObject(
        uri="nmap://10.0.0.5",
        content=b"Starting Nmap...\nPORT   STATE SERVICE\n22/tcp open  ssh\n",
        content_type="text/plain",
        fetched_at=datetime.now(UTC),
        extra={"target": "10.0.0.5"},
    )
    doc = NmapConnector().parse(raw)
    assert doc.title == "nmap scan: 10.0.0.5"
    assert "22/tcp open  ssh" in doc.text
    assert doc.extra["scan_target"] == "10.0.0.5"


def test_shodan_parse_summarizes_ports_org_and_hostnames():
    payload = {
        "ip_str": "203.0.113.7",
        "org": "Example Hosting Inc",
        "ports": [22, 443],
        "hostnames": ["host.example.com"],
        "data": [{"port": 443, "product": "nginx"}],
    }
    raw = RawObject(
        uri="shodan://203.0.113.7",
        content=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"target": "203.0.113.7"},
    )
    doc = ShodanConnector().parse(raw)
    assert doc.title == "Shodan exposure report: 203.0.113.7"
    assert "Example Hosting Inc" in doc.text
    assert "22, 443" in doc.text
    assert "host.example.com" in doc.text
    assert "Port 443 is running nginx." in doc.text


async def test_nmap_discover_accepts_engagement_id_kwarg():
    # api/routers/admin_connectors.py always folds `engagement_id` into
    # `job.params` once a requires_engagement=True connector has cleared the
    # PEP check, and ingestion/pipeline.py calls `discover(**params)` — a
    # discover() signature without this kwarg would raise on every real
    # invocation of this connector, not just look unused in review.
    items = [
        item
        async for item in NmapConnector().discover(
            target="10.0.0.5", engagement_id="eng_1", ports="22,443"
        )
    ]
    assert len(items) == 1
    assert items[0].ref == "10.0.0.5"
    assert items[0].extra["ports"] == "22,443"


async def test_shodan_discover_accepts_engagement_id_kwarg():
    items = [
        item async for item in ShodanConnector().discover(target="203.0.113.7", engagement_id="eng_1")
    ]
    assert len(items) == 1
    assert items[0].ref == "203.0.113.7"


def test_shodan_parse_handles_missing_fields_gracefully():
    payload = {"ip_str": "203.0.113.8"}
    raw = RawObject(
        uri="shodan://203.0.113.8",
        content=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        fetched_at=datetime.now(UTC),
        extra={"target": "203.0.113.8"},
    )
    doc = ShodanConnector().parse(raw)
    assert "none reported" in doc.text
