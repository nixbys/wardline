"""Collection-plane connector interface (report 4.1).

Every source — Wikipedia, SEC EDGAR, user uploads, the lawful web crawler, and
anything added later — implements this same four-method shape, so the
ingestion pipeline (ingestion/pipeline.py) never special-cases a source.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SourceItem:
    """Something discover() found that fetch() can retrieve."""

    ref: str  # connector-specific handle: a URL, a page title, a CIK+accession, ...
    hint_title: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class RawObject:
    """Exact bytes as fetched, before any parsing."""

    uri: str
    content: bytes
    content_type: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass
class ParsedDocument:
    """A common record shape the ingestion pipeline can normalize/chunk."""

    uri: str
    title: str
    text: str
    lang: str = "en"
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Provenance:
    uri: str
    fetched_at: datetime
    license: str
    content_hash: str
    source_connector: str


class Connector(ABC):
    """Base class every source connector implements.

    `discover()` may be a no-op generator for connectors that receive items
    directly (e.g. `upload`) rather than searching for them.
    """

    name: str
    default_license: str
    # Dual-use, target-lookup connectors (asset-exposure search engines,
    # breach-check APIs, aggregator tools) set this True; the admin
    # connector-run route then requires an active Engagement scoping the
    # requested target before the job is even queued (governance/pep.py:
    # enforce_engagement_scope). Public-corpus connectors (Wikipedia, SEC
    # EDGAR, archive.org, the crawler) leave this False — there's no
    # specific "target" being investigated, just a source being ingested.
    requires_engagement: bool = False

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    async def discover(self, **kwargs) -> AsyncIterator[SourceItem]:
        """Yield SourceItems to fetch. May take a bounded `**kwargs` query."""
        if False:  # pragma: no cover - makes this an async generator by shape
            yield SourceItem(ref="")

    @abstractmethod
    async def fetch(self, item: SourceItem) -> RawObject:
        """Retrieve raw bytes for one discovered item, with backoff on transient errors."""

    @abstractmethod
    def parse(self, raw: RawObject) -> ParsedDocument:
        """Turn raw bytes into a common, ingestion-ready record."""

    def provenance(self, item: SourceItem, raw: RawObject) -> Provenance:
        return Provenance(
            uri=raw.uri,
            fetched_at=raw.fetched_at,
            license=self.default_license,
            content_hash=raw.content_hash,
            source_connector=self.name,
        )
