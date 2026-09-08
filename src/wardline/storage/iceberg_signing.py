"""ML-DSA signing for the Iceberg audit export (commercialization roadmap
Phase 2 / Pillar 3.3) -- a real post-quantum *integrity* claim, distinct
from the vault's encryption claim (security/vault.py) and much cheaper to
add: sign, not encrypt.

`storage/iceberg_export.py` appends rows into a real Apache Iceberg table
(Parquet data files + manifests) -- not a discrete artifact naturally
suited to signing directly. Instead, each export run gets a small **receipt**
(snapshot id, row count, time range, a SHA-256 hash over the exported rows)
that gets ML-DSA-signed and persisted independently
(storage/models/iceberg.IcebergExportReceipt) -- something a customer or
auditor can verify offline, long after the fact, without needing to parse
Iceberg's own files or trust this deployment's *current* key (the public
key is denormalized onto every receipt row precisely so a receipt stays
verifiable under whichever key actually signed it, even after a later
rotation).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import mldsa

from wardline.common.config import get_settings
from wardline.storage.models.governance import AuditEvent

ALGORITHM = "ML-DSA-65"


def build_receipt(rows: list[AuditEvent], snapshot_id: str) -> dict:
    """A small, self-contained summary of one export batch -- built from
    the same ORM rows export_audit_events() already queried (not from the
    Arrow batch or Iceberg's own files), so this has no dependency on
    Iceberg/Arrow's internal representation ever staying byte-stable."""
    canonical = "\n".join(
        json.dumps(
            {
                "id": r.id,
                "session_id": r.session_id,
                "event_type": r.event_type,
                "user_id": r.user_id,
                "payload": r.payload,
                "created_at": r.created_at.isoformat(),
            },
            sort_keys=True,
        )
        for r in rows
    )
    return {
        "snapshot_id": snapshot_id,
        "row_count": len(rows),
        "time_range_start": rows[0].created_at,
        "time_range_end": rows[-1].created_at,
        "batch_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _canonical_receipt_bytes(receipt: dict) -> bytes:
    """What actually gets signed/verified -- every field a verifier would
    need to confirm this receipt matches a specific export and hasn't
    been replayed against a different one."""

    def _iso(value: datetime | str) -> str:
        return value.isoformat() if isinstance(value, datetime) else value

    return json.dumps(
        {
            "snapshot_id": receipt["snapshot_id"],
            "row_count": receipt["row_count"],
            "time_range_start": _iso(receipt["time_range_start"]),
            "time_range_end": _iso(receipt["time_range_end"]),
            "batch_sha256": receipt["batch_sha256"],
        },
        sort_keys=True,
    ).encode("utf-8")


def _load_signing_key() -> mldsa.MLDSA65PrivateKey | None:
    settings = get_settings()
    if not settings.iceberg_export_signing_enabled or not settings.iceberg_signing_key_seed:
        return None
    seed = base64.b64decode(settings.iceberg_signing_key_seed)
    return mldsa.MLDSA65PrivateKey.from_seed_bytes(seed)


def sign_receipt(receipt: dict) -> tuple[bytes, bytes] | None:
    """Returns (signature, public_key_bytes), or None if signing isn't
    configured (iceberg_export_signing_enabled off, or no key set yet --
    export_audit_events() still runs fine either way, it just doesn't
    persist a receipt for that run)."""
    key = _load_signing_key()
    if key is None:
        return None
    signature = key.sign(_canonical_receipt_bytes(receipt))
    return signature, key.public_key().public_bytes_raw()


def verify_receipt(receipt: dict, signature: bytes, public_key_bytes: bytes) -> bool:
    """For an external auditor or customer to check a receipt on its own
    -- doesn't read Settings or touch this deployment's current key at
    all, only what's passed in. A receipt is meant to be verifiable
    standalone, long after the deployment that produced it might have
    rotated keys."""
    public_key = mldsa.MLDSA65PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, _canonical_receipt_bytes(receipt))
    except InvalidSignature:
        return False
    return True


def generate_signing_keypair() -> tuple[str, str]:
    """Returns (seed_b64, public_key_b64) for a fresh ML-DSA-65 keypair.
    Called from the CLI (`wardline generate-iceberg-signing-key`), never
    at import time -- the seed goes into iceberg_signing_key_seed (a
    real secret), the public key gets published/documented for customers
    to verify receipts against."""
    key = mldsa.MLDSA65PrivateKey.generate()
    seed_b64 = base64.b64encode(key.private_bytes_raw()).decode("ascii")
    public_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    return seed_b64, public_b64
