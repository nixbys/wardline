"""Post-quantum integrity for the Iceberg audit export (commercialization
roadmap Phase 2 / Pillar 3.3): each export run gets a small, ML-DSA-signed
receipt over what was actually exported, independent of Iceberg's own
Parquet+manifest files (which aren't a natural thing to sign directly --
see storage/iceberg_signing.py for why a receipt exists as its own record
rather than trying to sign the table structure itself).
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class IcebergExportReceipt(Base, TimestampMixin):
    """One row per `export_audit_events()` run that actually exported
    something. `public_key` is denormalized onto every row (not just read
    from current Settings) so a receipt stays independently verifiable
    under the exact key that signed it, even after the signing key itself
    later rotates."""

    __tablename__ = "iceberg_export_receipts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "rcpt"))
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    time_range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    batch_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (Index("ix_iceberg_export_receipts_snapshot_id", "snapshot_id"),)
