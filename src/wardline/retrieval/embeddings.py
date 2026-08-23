"""Local embeddings (report 5.4/5.9): sentence-transformers, CPU, no paid API.
Same model class is used for both document and query embeddings, per the
report's explicit requirement — see `embed_texts`/`embed_query` both routing
through this one loader.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from wardline.common.config import get_settings


@lru_cache
def _model() -> SentenceTransformer:
    return SentenceTransformer(get_settings().embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def current_model_name() -> str:
    return get_settings().embedding_model
