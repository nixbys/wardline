"""Engagement lookups and target-scope matching for dual-use connectors.

`target_in_scope` covers two shapes, deliberately simple in both — a scope
check, not a fuzzy search:

- **Domain-shaped** targets: exact match (case-insensitive) or subdomain
  match. An engagement authorized for "acme.com" covers "www.acme.com" but
  never "notacme.com" or "acme.com.evil.example".
- **IP/CIDR-shaped** targets (added for active-scan connectors like
  `connectors/nmap_scan.py`, where engagements are routinely scoped to a
  network range rather than a single host): real containment via `ipaddress`,
  not string matching — an engagement for "10.0.0.0/24" covers "10.0.0.5" but
  never "10.0.1.5", and a single-host engagement like "203.0.113.7" is just
  the /32 case of the same check, so there's one code path for both instead
  of a second special case.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wardline.storage.models.engagements import Engagement


def _parse_network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        return None


def _parse_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def target_in_scope(engagement_target: str, requested_target: str) -> bool:
    engagement_target = engagement_target.strip().lower()
    requested_target = requested_target.strip().lower()

    network = _parse_network(engagement_target)
    if network is not None:
        address = _parse_address(requested_target)
        return address is not None and address in network

    if requested_target == engagement_target:
        return True
    return requested_target.endswith("." + engagement_target)


def get_engagement(db: Session, engagement_id: str) -> Engagement | None:
    return db.get(Engagement, engagement_id)


def is_active(engagement: Engagement, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if engagement.revoked_at is not None:
        return False
    return engagement.valid_from <= now <= engagement.valid_until


def revoke_engagement(db: Session, engagement_id: str) -> Engagement | None:
    engagement = db.get(Engagement, engagement_id)
    if engagement is None:
        return None
    engagement.revoked_at = datetime.now(UTC)
    db.flush()
    return engagement
