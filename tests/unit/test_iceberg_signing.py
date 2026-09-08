"""Unit coverage for storage/iceberg_signing.py (commercialization roadmap
Phase 2 / Pillar 3.3). All pure functions -- AuditEvent rows are
constructed in memory (no db.add/flush needed, matching test_audit.py's
convention), and signing config comes from monkeypatching get_settings
rather than a real deployment secret.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wardline.storage import iceberg_signing
from wardline.storage.models.governance import AuditEvent

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _rows() -> list[AuditEvent]:
    return [
        AuditEvent(
            id=f"aud_{i}",
            session_id="qs_1",
            event_type="query_opened",
            user_id="u1",
            payload={"question": f"question {i}", "mode": "auto"},
            created_at=_T0 + timedelta(minutes=i),
        )
        for i in range(3)
    ]


def test_build_receipt_summarizes_the_batch():
    rows = _rows()
    receipt = iceberg_signing.build_receipt(rows, "snap_123")
    assert receipt["snapshot_id"] == "snap_123"
    assert receipt["row_count"] == 3
    assert receipt["time_range_start"] == rows[0].created_at
    assert receipt["time_range_end"] == rows[-1].created_at
    assert len(receipt["batch_sha256"]) == 64  # hex sha256


def test_build_receipt_hash_changes_if_a_row_changes():
    rows = _rows()
    receipt1 = iceberg_signing.build_receipt(rows, "snap_123")
    rows[0].payload = {"question": "a different question", "mode": "auto"}
    receipt2 = iceberg_signing.build_receipt(rows, "snap_123")
    assert receipt1["batch_sha256"] != receipt2["batch_sha256"]


def test_generate_signing_keypair_round_trips_through_sign_and_verify():
    seed_b64, public_b64 = iceberg_signing.generate_signing_keypair()
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")

    import base64

    from cryptography.hazmat.primitives.asymmetric import mldsa

    key = mldsa.MLDSA65PrivateKey.from_seed_bytes(base64.b64decode(seed_b64))
    signature = key.sign(iceberg_signing._canonical_receipt_bytes(receipt))
    assert iceberg_signing.verify_receipt(receipt, signature, base64.b64decode(public_b64)) is True


def test_verify_receipt_rejects_a_tampered_receipt():
    seed_b64, public_b64 = iceberg_signing.generate_signing_keypair()
    import base64

    from cryptography.hazmat.primitives.asymmetric import mldsa

    key = mldsa.MLDSA65PrivateKey.from_seed_bytes(base64.b64decode(seed_b64))
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")
    signature = key.sign(iceberg_signing._canonical_receipt_bytes(receipt))

    tampered = dict(receipt, row_count=receipt["row_count"] + 1)
    assert iceberg_signing.verify_receipt(tampered, signature, base64.b64decode(public_b64)) is False


def test_verify_receipt_rejects_the_wrong_public_key():
    seed2, _pub2 = iceberg_signing.generate_signing_keypair()
    _wrong_seed, wrong_pub = iceberg_signing.generate_signing_keypair()

    import base64

    from cryptography.hazmat.primitives.asymmetric import mldsa

    key2 = mldsa.MLDSA65PrivateKey.from_seed_bytes(base64.b64decode(seed2))
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")
    signature = key2.sign(iceberg_signing._canonical_receipt_bytes(receipt))

    assert iceberg_signing.verify_receipt(receipt, signature, base64.b64decode(wrong_pub)) is False


def test_sign_receipt_returns_none_when_signing_is_disabled(monkeypatch):
    from wardline.common.config import Settings, get_settings

    def _disabled_settings():
        s = get_settings()
        return Settings(**{**s.model_dump(), "iceberg_export_signing_enabled": False})

    monkeypatch.setattr(iceberg_signing, "get_settings", _disabled_settings)
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")
    assert iceberg_signing.sign_receipt(receipt) is None


def test_sign_receipt_returns_none_with_no_key_seed_even_if_enabled(monkeypatch):
    from wardline.common.config import Settings, get_settings

    def _enabled_no_seed():
        s = get_settings()
        return Settings(
            **{**s.model_dump(), "iceberg_export_signing_enabled": True, "iceberg_signing_key_seed": None}
        )

    monkeypatch.setattr(iceberg_signing, "get_settings", _enabled_no_seed)
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")
    assert iceberg_signing.sign_receipt(receipt) is None


def test_sign_receipt_end_to_end_when_configured(monkeypatch):
    from wardline.common.config import Settings, get_settings

    seed_b64, public_b64 = iceberg_signing.generate_signing_keypair()

    def _configured():
        s = get_settings()
        return Settings(
            **{
                **s.model_dump(),
                "iceberg_export_signing_enabled": True,
                "iceberg_signing_key_seed": seed_b64,
            }
        )

    monkeypatch.setattr(iceberg_signing, "get_settings", _configured)
    receipt = iceberg_signing.build_receipt(_rows(), "snap_123")
    signed = iceberg_signing.sign_receipt(receipt)
    assert signed is not None
    signature, public_key = signed

    import base64

    assert public_key == base64.b64decode(public_b64)
    assert iceberg_signing.verify_receipt(receipt, signature, public_key) is True
