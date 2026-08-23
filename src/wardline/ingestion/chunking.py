"""Structural chunker (report 5.4): splits on line breaks first, then packs
lines into ~300-800 token windows with 10-20% overlap, recording exact
`char_start`/`char_end` so citations can point to precise spans. Any single
unit that alone exceeds the max (e.g. a long table block with no internal
newlines) is hard-split on token boundaries so no chunk ever exceeds
`chunk_max_tokens`, regardless of the source's paragraph structure.

Token counts use tiktoken's cl100k encoding purely as a stable, model-agnostic
proxy for "how much text fits in a context window" — not tied to any one
embedding/LLM's actual tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tiktoken

from wardline.common.config import get_settings

_ENCODING = tiktoken.get_encoding("cl100k_base")
_LINE_RE = re.compile(r"\n+")


@dataclass
class ChunkSpan:
    text: str
    ordinal: int
    char_start: int
    char_end: int


def _split_units(text: str) -> list[tuple[str, int, int]]:
    """Return (text, start, end) for each non-empty line/paragraph unit."""
    units: list[tuple[str, int, int]] = []
    pos = 0
    for line in _LINE_RE.split(text):
        start = text.index(line, pos) if line else pos
        stripped = line.strip()
        if stripped:
            local_start = start + line.index(stripped)
            local_end = local_start + len(stripped)
            units.append((stripped, local_start, local_end))
        pos = start + len(line)
    return units


def _token_count(text: str) -> int:
    return len(_ENCODING.encode(text))


def _hard_split(unit_text: str, offset: int, max_tokens: int) -> list[tuple[str, int, int]]:
    """Token-window slice a single oversized unit so no piece exceeds max_tokens.

    Decoding a prefix of the token list is guaranteed to be an exact prefix of
    the original text (cl100k round-trips exactly), so char offsets from
    `len(decoded_prefix)` are exact, not approximate.
    """
    tokens = _ENCODING.encode(unit_text)
    pieces: list[tuple[str, int, int]] = []
    prev_char_len = 0
    for i in range(0, len(tokens), max_tokens):
        end_token = min(i + max_tokens, len(tokens))
        decoded_upto_end = _ENCODING.decode(tokens[:end_token])
        piece_text = decoded_upto_end[prev_char_len:]
        piece_start = offset + prev_char_len
        piece_end = offset + len(decoded_upto_end)
        pieces.append((piece_text, piece_start, piece_end))
        prev_char_len = len(decoded_upto_end)
    return pieces


def chunk_text(text: str) -> list[ChunkSpan]:
    settings = get_settings()
    raw_units = _split_units(text)
    if not raw_units:
        return []

    # Guarantee every unit fits within max_tokens before packing.
    units: list[tuple[str, int, int]] = []
    for unit_text, start, end in raw_units:
        if _token_count(unit_text) > settings.chunk_max_tokens:
            units.extend(_hard_split(unit_text, start, settings.chunk_max_tokens))
        else:
            units.append((unit_text, start, end))

    chunks: list[ChunkSpan] = []
    ordinal = 0
    i = 0
    n = len(units)

    while i < n:
        window: list[tuple[str, int, int]] = []
        tokens = 0
        j = i
        while j < n:
            unit_tokens = _token_count(units[j][0])
            if tokens > 0 and tokens + unit_tokens > settings.chunk_max_tokens:
                break
            window.append(units[j])
            tokens += unit_tokens
            j += 1
            if tokens >= settings.chunk_target_tokens:
                break

        chunk_text_value = "\n".join(u[0] for u in window)
        chunks.append(
            ChunkSpan(
                text=chunk_text_value,
                ordinal=ordinal,
                char_start=window[0][1],
                char_end=window[-1][2],
            )
        )
        ordinal += 1

        if j >= n:
            break

        # Overlap: back up by roughly `chunk_overlap_ratio` of the window's
        # tokens, measured in whole units, so the next chunk repeats the tail
        # of this one instead of starting cold. Capped at len(window) - 1 so
        # `i` always advances by at least one unit — otherwise a window made
        # of a single (large) unit would never make progress.
        overlap_budget = tokens * settings.chunk_overlap_ratio
        back = 0
        overlap_tokens = 0
        max_back = len(window) - 1
        for u in reversed(window):
            if back >= max_back:
                break
            u_tokens = _token_count(u[0])
            if overlap_tokens + u_tokens > overlap_budget and back > 0:
                break
            overlap_tokens += u_tokens
            back += 1
        i = j - back

    return chunks
