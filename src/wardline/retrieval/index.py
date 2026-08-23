"""Turns a stored Document's cleaned text into indexed Chunk rows: chunk,
embed, persist. `tsv` (lexical) is a DB-generated column, so inserting the
row is all that's needed to make it lexically searchable too -- unless
`settings.lexical_backend == "opensearch"`, in which case each chunk is
also written to the real OpenSearch index (retrieval/opensearch_backend.py)
alongside the Postgres row; the tsv column is harmless dead weight in that
mode, not removed, since switching back never loses data.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.ingestion.chunking import chunk_text
from wardline.ingestion.pii import tag_pii
from wardline.retrieval.embeddings import current_model_name, embed_texts
from wardline.storage.models.chunks import Chunk
from wardline.storage.models.documents import Document

logger = get_logger(__name__)


def index_document(db: Session, doc_id: str, text: str) -> list[str]:
    spans = chunk_text(text)
    if not spans:
        return []

    embeddings = embed_texts([s.text for s in spans])
    model_name = current_model_name()
    use_opensearch = get_settings().lexical_backend == "opensearch"
    doc = db.get(Document, doc_id) if use_opensearch else None

    chunk_ids = []
    for span, embedding in zip(spans, embeddings, strict=True):
        chunk = Chunk(
            doc_id=doc_id,
            text=span.text,
            ordinal=span.ordinal,
            char_start=span.char_start,
            char_end=span.char_end,
            embedding=embedding,
            embedding_model=model_name,
            pii_tags=tag_pii(span.text),
        )
        db.add(chunk)
        db.flush()
        chunk_ids.append(chunk.id)

        if use_opensearch and doc is not None:
            from wardline.retrieval.opensearch_backend import index_chunk

            index_chunk(chunk.id, doc_id, span.text, doc.lang, doc.status, doc.published_at)

    logger.info("index.document_indexed", doc_id=doc_id, chunk_count=len(chunk_ids))
    return chunk_ids
