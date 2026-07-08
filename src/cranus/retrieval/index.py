"""Turns a stored Document's cleaned text into indexed Chunk rows: chunk,
embed, persist. `tsv` (lexical) is a DB-generated column, so inserting the
row is all that's needed to make it lexically searchable too.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cranus.common.logging import get_logger
from cranus.ingestion.chunking import chunk_text
from cranus.ingestion.pii import tag_pii
from cranus.retrieval.embeddings import current_model_name, embed_texts
from cranus.storage.models.chunks import Chunk

logger = get_logger(__name__)


def index_document(db: Session, doc_id: str, text: str) -> list[str]:
    spans = chunk_text(text)
    if not spans:
        return []

    embeddings = embed_texts([s.text for s in spans])
    model_name = current_model_name()

    chunk_ids = []
    for span, embedding in zip(spans, embeddings):
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

    logger.info("index.document_indexed", doc_id=doc_id, chunk_count=len(chunk_ids))
    return chunk_ids
