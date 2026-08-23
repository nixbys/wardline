"""Runs the real faster-whisper "tiny" model (local, no external account,
downloaded from the HF Hub on first use) end-to-end against a synthetic
WAV -- this is a genuine smoke test of the decode->transcribe pipeline
(tempfile handling, PyAV/ffmpeg container decoding, model invocation,
segment-joining), not a transcription-accuracy test: the input is a pure
tone, not speech, so there is no expected text to assert against.
"""

from __future__ import annotations

import io
import wave

from wardline.ingestion.extractors.audio import transcribe_audio


def _make_wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    n_samples = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(b"\x00\x00" * n_samples)  # silence
    return buf.getvalue()


def test_transcribe_audio_runs_end_to_end_on_a_real_wav_file():
    result = transcribe_audio(_make_wav_bytes())
    assert isinstance(result.text, str)
    assert isinstance(result.language, str) and result.language
    assert result.duration_seconds == 1.0
