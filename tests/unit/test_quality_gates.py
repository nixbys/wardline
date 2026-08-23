from wardline.ingestion.quality_gates import check_document


def test_empty_text_fails():
    result = check_document("", "CC-BY-SA-4.0")
    assert not result.passed
    assert result.reason == "empty_or_too_short"


def test_unknown_license_fails():
    result = check_document("A perfectly good long piece of article text.", "some-made-up-license")
    assert not result.passed
    assert "unknown_license" in result.reason


def test_valid_document_passes():
    result = check_document(
        "A perfectly good long piece of article text that clears the minimum length.",
        "CC-BY-SA-4.0",
    )
    assert result.passed
    assert result.reason is None
