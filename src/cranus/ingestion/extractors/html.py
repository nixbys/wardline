"""HTML boilerplate removal (report 4.2): strip nav/ads/chrome, keep main content."""

from __future__ import annotations

from dataclasses import dataclass

import trafilatura


@dataclass
class ExtractedHtml:
    text: str
    title: str | None
    author: str | None = None


def extract_html(content: bytes, url: str | None = None) -> ExtractedHtml:
    downloaded = content.decode("utf-8", errors="replace")
    result = trafilatura.bare_extraction(
        downloaded,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        as_dict=True,
    )
    if result is None:
        return ExtractedHtml(text="", title=None)
    return ExtractedHtml(
        text=result.get("text") or "",
        title=result.get("title"),
        author=result.get("author"),
    )
