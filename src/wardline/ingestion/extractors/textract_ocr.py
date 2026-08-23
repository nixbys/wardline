"""AWS Textract OCR backend -- the noted "Cloud/commercial OCR" upgrade
path from local Tesseract (see the README's scope-reductions table).
Local Tesseract is adequate for typed/scanned filings but struggles on
messier scans and handwriting; Textract handles both meaningfully better.

Selected via `settings.ocr_backend = "textract"`. Requires real AWS
credentials via boto3's standard credential chain (env vars,
`~/.aws/credentials`, or an IAM role) -- this repo has no AWS account to
supply one, so this module is code-reviewed and unit-tested against a
mocked boto3 client (`tests/unit/test_textract_ocr.py`), not live-tested
against the real Textract API. That's a real limitation, not hidden: an
operator switching this on should run one document through it by hand
before relying on it in production.
"""

from __future__ import annotations

from functools import lru_cache

from wardline.common.config import get_settings


@lru_cache
def _client():
    import boto3

    return boto3.client("textract", region_name=get_settings().textract_region)


def ocr_image_via_textract(image_bytes: bytes) -> str:
    """Runs AWS Textract's synchronous DetectDocumentText on a single
    rasterized page image (PNG/JPEG bytes, <=10MB per Textract's own
    limit) and returns the page's text, line breaks preserved.
    """
    response = _client().detect_document_text(Document={"Bytes": image_bytes})
    lines = [block["Text"] for block in response.get("Blocks", []) if block.get("BlockType") == "LINE"]
    return "\n".join(lines)
