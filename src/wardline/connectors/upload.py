"""Bring-your-own-corpus connector: no `discover()` phase — the upload API
route hands a SourceItem with the file bytes already attached straight to
`fetch()`/`parse()`. MIME detection via `filetype` (pure Python, no libmagic
system dependency).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import filetype

from wardline.connectors.base import Connector, ParsedDocument, RawObject, SourceItem
from wardline.connectors.registry import register_connector

LICENSE = "user-uploaded"


@register_connector("upload")
class UploadConnector(Connector):
    default_license = LICENSE

    async def discover(self, **kwargs) -> AsyncIterator[SourceItem]:
        return
        yield  # pragma: no cover - makes this an async generator; upload never discovers

    async def fetch(self, item: SourceItem) -> RawObject:
        content: bytes = item.extra["content"]
        kind = filetype.guess(content)
        content_type = kind.mime if kind else item.extra.get("content_type", "text/plain")
        return RawObject(
            uri=item.ref,
            content=content,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            extra={"filename": item.extra.get("filename", item.ref), "license": item.extra.get("license")},
        )

    def parse(self, raw: RawObject) -> ParsedDocument:
        if raw.content_type == "application/pdf":
            from wardline.ingestion.extractors.pdf import extract_pdf

            text = extract_pdf(raw.content).text
        elif raw.content_type in ("text/html", "application/xhtml+xml"):
            from wardline.ingestion.extractors.html import extract_html

            text = extract_html(raw.content).text
        elif raw.content_type == "application/json":
            from wardline.ingestion.extractors.structured import extract_json

            text = extract_json(raw.content).text
        elif raw.content_type.startswith("audio/") or raw.content_type.startswith("video/"):
            from wardline.ingestion.extractors.audio import transcribe_audio

            text = transcribe_audio(raw.content).text
        else:
            text = raw.content.decode("utf-8", errors="replace")

        return ParsedDocument(
            uri=raw.uri,
            title=raw.extra.get("filename", raw.uri),
            text=text,
            lang="en",
            published_at=None,
            extra={},
        )

    def provenance(self, item: SourceItem, raw: RawObject):
        prov = super().provenance(item, raw)
        if raw.extra.get("license"):
            prov.license = raw.extra["license"]
        return prov
