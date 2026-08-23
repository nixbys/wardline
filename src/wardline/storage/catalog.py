"""Helpers for the `sources` catalog table (report 4.3's lightweight data catalog)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.storage.models.base import utcnow
from wardline.storage.models.ingestion import Source


def register_source(db: Session, name: str, default_license: str, config_schema: dict) -> Source:
    existing = db.get(Source, name)
    if existing:
        existing.default_license = default_license
        existing.config_schema = config_schema
        return existing
    source = Source(name=name, default_license=default_license, config_schema=config_schema)
    db.add(source)
    return source


def record_run(db: Session, name: str, rows_added: int) -> None:
    source = db.get(Source, name)
    if source is None:
        return
    source.last_run_at = utcnow()
    source.row_count += rows_added


def list_sources(db: Session) -> list[Source]:
    return list(db.execute(select(Source)).scalars())
