"""Engagement lookups and target-scope matching for dual-use connectors.

`target_in_scope` is deliberately simple: exact match (case-insensitive) or
subdomain match for domain-shaped targets. It's a scope check, not a fuzzy
search — an engagement authorized for "acme.com" should cover "www.acme.com"
but should never be interpreted loosely enough to cover "notacme.com" or
"acme.com.evil.example".
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from cranus.storage.models.engagements import Engagement


def target_in_scope(engagement_target: str, requested_target: str) -> bool:
    engagement_target = engagement_target.strip().lower()
    requested_target = requested_target.strip().lower()
    if requested_target == engagement_target:
        return True
    return requested_target.endswith("." + engagement_target)


def get_engagement(db: Session, engagement_id: str) -> Engagement | None:
    return db.get(Engagement, engagement_id)


def is_active(engagement: Engagement, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if engagement.revoked_at is not None:
        return False
    return engagement.valid_from <= now <= engagement.valid_until


def revoke_engagement(db: Session, engagement_id: str) -> Engagement | None:
    engagement = db.get(Engagement, engagement_id)
    if engagement is None:
        return None
    engagement.revoked_at = datetime.now(timezone.utc)
    db.flush()
    return engagement
