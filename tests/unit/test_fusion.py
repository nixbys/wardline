from wardline.retrieval.fusion import rrf_merge
from wardline.retrieval.lexical import RetrievedChunk


def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=cid, doc_id="doc_1", text=f"text for {cid}", score=1.0)


def test_rrf_merges_and_ranks_by_combined_rank():
    lexical = [_chunk("a"), _chunk("b"), _chunk("c")]
    vector = [_chunk("b"), _chunk("a"), _chunk("d")]

    fused = rrf_merge(lexical, vector)
    ids = [f.chunk_id for f in fused]

    # "a" and "b" appear near the top of both lists, so they should outrank
    # "c" and "d", which each appear in only one list.
    assert set(ids[:2]) == {"a", "b"}
    assert ids[2:] == sorted(ids[2:])[::-1] or set(ids[2:]) == {"c", "d"}


def test_rrf_dedupes_by_chunk_id():
    lexical = [_chunk("a"), _chunk("a")]
    fused = rrf_merge(lexical)
    assert len(fused) == 1


def test_rrf_empty_input():
    assert rrf_merge() == []
