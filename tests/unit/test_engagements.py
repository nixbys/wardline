from datetime import UTC, datetime, timedelta

import pytest

from wardline.common.errors import AccessDeniedError
from wardline.governance import pep
from wardline.governance.engagements import is_active, target_in_scope
from wardline.storage.models.engagements import Engagement


def _engagement(**overrides) -> Engagement:
    now = datetime.now(UTC)
    defaults = {
        "id": "eng_1",
        "target": "acme.com",
        "scope_note": "external footprint assessment",
        "evidence_ref": "SOW-2026-001",
        "authorized_by_user_id": "user_1",
        "valid_from": now - timedelta(days=1),
        "valid_until": now + timedelta(days=30),
        "revoked_at": None,
    }
    defaults.update(overrides)
    return Engagement(**defaults)


def test_target_in_scope_exact_match():
    assert target_in_scope("acme.com", "ACME.com")


def test_target_in_scope_subdomain_match():
    assert target_in_scope("acme.com", "www.acme.com")


def test_target_in_scope_rejects_unrelated_domain():
    assert not target_in_scope("acme.com", "notacme.com")


def test_target_in_scope_rejects_suffix_spoof():
    assert not target_in_scope("acme.com", "acme.com.evil.example")


def test_target_in_scope_cidr_contains_address():
    assert target_in_scope("10.0.0.0/24", "10.0.0.5")


def test_target_in_scope_cidr_rejects_out_of_range_address():
    assert not target_in_scope("10.0.0.0/24", "10.0.1.5")


def test_target_in_scope_single_ip_is_the_slash_32_case():
    assert target_in_scope("203.0.113.7", "203.0.113.7")
    assert not target_in_scope("203.0.113.7", "203.0.113.8")


def test_target_in_scope_cidr_rejects_non_ip_request():
    assert not target_in_scope("10.0.0.0/24", "not-an-ip")


def test_is_active_true_within_window():
    assert is_active(_engagement())


def test_is_active_false_when_revoked():
    now = datetime.now(UTC)
    assert not is_active(_engagement(revoked_at=now))


def test_is_active_false_when_expired():
    now = datetime.now(UTC)
    engagement = _engagement(valid_from=now - timedelta(days=10), valid_until=now - timedelta(days=1))
    assert not is_active(engagement)


def test_is_active_false_before_start():
    now = datetime.now(UTC)
    engagement = _engagement(valid_from=now + timedelta(days=1), valid_until=now + timedelta(days=10))
    assert not is_active(engagement)


class _FakeDb:
    def __init__(self, engagement: Engagement | None):
        self._engagement = engagement

    def get(self, model, engagement_id):
        return self._engagement


def test_enforce_engagement_scope_requires_engagement_id():
    with pytest.raises(AccessDeniedError, match="requires an engagement_id"):
        pep.enforce_engagement_scope(_FakeDb(None), None, "acme.com")


def test_enforce_engagement_scope_rejects_unknown_engagement():
    with pytest.raises(AccessDeniedError, match="no such engagement"):
        pep.enforce_engagement_scope(_FakeDb(None), "eng_missing", "acme.com")


def test_enforce_engagement_scope_rejects_revoked():
    now = datetime.now(UTC)
    db = _FakeDb(_engagement(revoked_at=now))
    with pytest.raises(AccessDeniedError, match="revoked or outside"):
        pep.enforce_engagement_scope(db, "eng_1", "acme.com")


def test_enforce_engagement_scope_rejects_out_of_scope_target():
    db = _FakeDb(_engagement())
    with pytest.raises(AccessDeniedError, match="outside engagement"):
        pep.enforce_engagement_scope(db, "eng_1", "notacme.com")


def test_enforce_engagement_scope_allows_valid_request():
    db = _FakeDb(_engagement())
    pep.enforce_engagement_scope(db, "eng_1", "www.acme.com")  # does not raise
