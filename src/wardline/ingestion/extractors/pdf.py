"""PDF text extraction with an OCR fallback for scanned pages (report 4.2).

Heuristic: if a page's text layer yields fewer than `MIN_CHARS_PER_PAGE`
characters, treat it as scanned and rasterize+OCR that page instead. Real
OCR, not stubbed — local Tesseract by default (adequate for typed/scanned
filings, not handwriting), or AWS Textract (`settings.ocr_backend =
"textract"`, see `textract_ocr.py`) for higher accuracy on messier scans.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from pdf2image import convert_from_bytes
from pypdf import PdfReader

from wardline.common.config import get_settings

MIN_CHARS_PER_PAGE = 50


@dataclass
class ExtractedPdf:
    text: str
    pages: int
    ocr_pages: int


def _ocr_image(image) -> str:
    if get_settings().ocr_backend == "textract":
        from wardline.ingestion.extractors.textract_ocr import ocr_image_via_textract

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return ocr_image_via_textract(buf.getvalue())

    import pytesseract

    return pytesseract.image_to_string(image)


def extract_pdf(content: bytes) -> ExtractedPdf:
    reader = PdfReader(io.BytesIO(content))
    page_texts: list[str] = []
    ocr_page_indices: list[int] = []

    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if len(text) < MIN_CHARS_PER_PAGE:
            ocr_page_indices.append(i)
            page_texts.append("")  # placeholder, filled in below if OCR succeeds
        else:
            page_texts.append(text)

    if ocr_page_indices:
        images = convert_from_bytes(content, dpi=200)
        for i in ocr_page_indices:
            if i < len(images):
                page_texts[i] = _ocr_image(images[i])

    return ExtractedPdf(
        text="\n\n".join(t for t in page_texts if t),
        pages=len(reader.pages),
        ocr_pages=len(ocr_page_indices),
    )
