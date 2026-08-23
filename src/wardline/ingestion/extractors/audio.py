"""Local speech-to-text via faster-whisper (CTranslate2-backed Whisper) --
the report's "Full ASR pipeline" scope-reduction item, closed as a local,
open-source model rather than a cloud ASR API, matching this project's
existing stance on embeddings/reranking (local models, no paid API by
default). Handles both audio and video containers: faster-whisper decodes
through PyAV/ffmpeg internally, so a video file's audio track is extracted
automatically -- no separate video-to-audio step needed.

Reachable through the `upload` connector (`connectors/upload.py`), the
same bring-your-own-corpus path already used for PDFs/HTML/JSON: this adds
a transcription step to that lawful, user-provided-data pathway, not a new
scraping-style connector against a third-party platform's audio/video
(which would raise the same ToS/legal questions "The legal boundary" in
the README already explains this project declines to cross).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from functools import lru_cache

from wardline.common.config import get_settings


@dataclass
class Transcript:
    text: str
    language: str
    duration_seconds: float


@lru_cache
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(get_settings().asr_model, device="cpu", compute_type="int8")


def transcribe_audio(content: bytes) -> Transcript:
    """`content` is the raw file bytes of an audio or video file in any
    container faster-whisper/ffmpeg can decode. Written to a temp file
    since faster-whisper's decoder needs a seekable path, not a bytes blob.
    """
    with tempfile.NamedTemporaryFile(suffix=".media") as f:
        f.write(content)
        f.flush()
        segments, info = _model().transcribe(f.name)
        text = " ".join(segment.text.strip() for segment in segments)
    return Transcript(text=text, language=info.language, duration_seconds=info.duration)
