"""No real AWS account is available in this environment (see the
textract_ocr.py module docstring), so this exercises the module two ways:
against moto's simulated Textract (proves the real botocore call shape --
`Document={"Bytes": ...}` -- is accepted, the same request the real API
would receive) and against a hand-built response (proves the LINE-block
text-joining logic, which moto's stub can't exercise since it always
returns an empty Blocks list).
"""

from __future__ import annotations

from moto import mock_aws

from wardline.ingestion.extractors.textract_ocr import _client, ocr_image_via_textract


def test_real_botocore_call_shape_is_accepted_by_textract():
    _client.cache_clear()
    with mock_aws():
        # moto's DetectDocumentText stub always returns an empty Blocks list --
        # this confirms the call itself is well-formed, not the text extracted.
        assert ocr_image_via_textract(b"fake-png-bytes") == ""
    _client.cache_clear()


def test_joins_line_blocks_and_ignores_other_block_types(monkeypatch):
    class _FakeClient:
        def detect_document_text(self, Document):
            assert set(Document.keys()) == {"Bytes"}
            return {
                "Blocks": [
                    {"BlockType": "PAGE", "Text": None},
                    {"BlockType": "LINE", "Text": "Acme Corp Annual Report"},
                    {"BlockType": "WORD", "Text": "Acme"},
                    {"BlockType": "LINE", "Text": "Fiscal Year 2026"},
                ]
            }

    import wardline.ingestion.extractors.textract_ocr as mod

    monkeypatch.setattr(mod, "_client", lambda: _FakeClient())
    result = ocr_image_via_textract(b"fake-png-bytes")
    assert result == "Acme Corp Annual Report\nFiscal Year 2026"
