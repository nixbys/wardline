from wardline.query.verify import verify_citations


def test_empty_answer_is_insufficient_evidence():
    result = verify_citations("", {"chunk_1"})
    assert result.insufficient_evidence
    assert result.text == ""


def test_sentence_with_valid_citation_is_kept():
    answer = "Acme Corp was founded in 2011 [chunk_1]."
    result = verify_citations(answer, {"chunk_1"})

    assert not result.insufficient_evidence
    assert len(result.claims) == 1
    assert result.claims[0].supported_by == ["chunk_1"]
    assert "chunk_1" in result.text


def test_sentence_with_fabricated_citation_is_dropped():
    answer = "Acme Corp was founded in 2011 [chunk_999]."
    result = verify_citations(answer, {"chunk_1"})

    assert result.insufficient_evidence
    assert result.claims == []


def test_mixed_sentences_keep_only_cited_ones():
    answer = "Acme Corp was founded in 2011 [chunk_1]. This sentence has no citation at all."
    result = verify_citations(answer, {"chunk_1"})

    assert not result.insufficient_evidence
    assert len(result.claims) == 1
    assert "no citation at all" not in result.text


def test_citation_bracket_stays_with_its_own_sentence():
    # Regression test: citations were previously shifting onto the *next*
    # sentence when the bracket followed a ". " boundary. This is the format
    # both the mock synthesizer and a real LLM naturally produce.
    answer = "First fact here [chunk_1]. Second fact here [chunk_2]."
    result = verify_citations(answer, {"chunk_1", "chunk_2"})

    assert len(result.claims) == 2
    assert result.claims[0].supported_by == ["chunk_1"]
    assert result.claims[1].supported_by == ["chunk_2"]
    assert "First fact" in result.claims[0].text
    assert "Second fact" in result.claims[1].text
