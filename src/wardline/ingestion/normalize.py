"""Normalization steps (report 4.2): language detection, encoding cleanup,
near-duplicate detection via MinHash so syndicated content doesn't flood the
index.
"""

from __future__ import annotations

from datasketch import MinHash
from ftfy import fix_text
from langdetect import LangDetectException, detect

MINHASH_NUM_PERM = 128
NGRAM_SIZE = 5


def clean_text(text: str) -> str:
    return fix_text(text).strip()


def detect_language(text: str) -> str:
    try:
        return detect(text[:2000]) if text.strip() else "en"
    except LangDetectException:
        return "en"


def minhash_signature(text: str) -> MinHash:
    mh = MinHash(num_perm=MINHASH_NUM_PERM)
    words = text.split()
    shingles = {" ".join(words[i : i + NGRAM_SIZE]) for i in range(max(len(words) - NGRAM_SIZE + 1, 1))}
    for shingle in shingles:
        mh.update(shingle.encode("utf-8"))
    return mh


def is_near_duplicate(a: MinHash, b: MinHash, threshold: float = 0.85) -> bool:
    return a.jaccard(b) >= threshold
