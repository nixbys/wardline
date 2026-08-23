from wardline.ingestion.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_offsets_are_exact_substrings():
    para = "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do eiusmod tempor incididunt."
    text = "\n".join(f"{para} Paragraph number {i}." for i in range(60))

    spans = chunk_text(text)

    assert len(spans) > 1
    for span in spans:
        assert text[span.char_start : span.char_end] == span.text


def test_consecutive_chunks_overlap():
    para = "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do eiusmod tempor incididunt."
    text = "\n".join(f"{para} Paragraph number {i}." for i in range(60))

    spans = chunk_text(text)

    assert spans[1].char_start < spans[0].char_end


def test_oversized_single_line_is_hard_split_without_hanging():
    # A single "paragraph" (no internal newlines) far larger than max_tokens.
    # This is the exact shape that previously caused an infinite loop.
    text = "word " * 20000
    spans = chunk_text(text)

    assert len(spans) > 1
    for span in spans:
        assert text[span.char_start : span.char_end] == span.text
    # Full coverage: every character ends up in some chunk.
    assert spans[0].char_start == 0
    assert spans[-1].char_end == len(text.rstrip())
