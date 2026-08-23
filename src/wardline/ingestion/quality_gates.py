"""Quality gates (report 4.2): records that fail validation are quarantined,
not silently indexed.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_DOCUMENT_CHARS = 40
KNOWN_LICENSES = {
    "CC-BY-SA-4.0",
    "us-gov-open-data",
    "user-uploaded",
    "open-web-crawled",
    "public-archive-snapshot",
    "CC0-1.0",
    "odbl-opencorporates",
    "gov-open-data-v1",
    "internal-only",
}


@dataclass
class QualityResult:
    passed: bool
    reason: str | None = None


def check_document(text: str, license: str) -> QualityResult:
    if not text or len(text.strip()) < MIN_DOCUMENT_CHARS:
        return QualityResult(passed=False, reason="empty_or_too_short")
    if license not in KNOWN_LICENSES:
        return QualityResult(passed=False, reason=f"unknown_license:{license}")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return QualityResult(passed=False, reason="invalid_encoding")
    return QualityResult(passed=True)
