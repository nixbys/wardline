"""Structured (CSV/JSON/XML) -> flat text + metadata, for structured connector
output (e.g. SEC XBRL/JSON company facts) that still needs to flow through the
same chunk/embed/index pipeline as prose documents.
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class ExtractedStructured:
    text: str
    record_count: int


def extract_json(content: bytes) -> ExtractedStructured:
    obj = json.loads(content)
    return ExtractedStructured(text=json.dumps(obj, indent=2, default=str), record_count=1)


def extract_csv(content: bytes) -> ExtractedStructured:
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    lines = [", ".join(f"{k}: {v}" for k, v in row.items()) for row in rows]
    return ExtractedStructured(text="\n".join(lines), record_count=len(rows))


def extract_xml(content: bytes) -> ExtractedStructured:
    root = ET.fromstring(content)
    lines = ["".join(elem.itertext()).strip() for elem in root.iter() if elem.text and elem.text.strip()]
    return ExtractedStructured(text="\n".join(lines), record_count=len(lines))
