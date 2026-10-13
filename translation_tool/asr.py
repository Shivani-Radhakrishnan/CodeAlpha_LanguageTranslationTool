"""Speech recognition with Whisper (faster-whisper / CTranslate2, int8 on CPU; no PyTorch).

The "base" model (about 145 MB) is downloaded on first use. Whisper detects the spoken
language itself, so speech-to-speech translation needs no source-language choice.
"""
from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

MODEL_SIZE = "base"

# Whisper language codes that differ from Google Translate's.
_WHISPER_TO_GOOGLE = {"he": "iw", "zh": "zh-CN", "jw": "jw", "haw": "haw"}
_GOOGLE_TO_WHISPER = {"iw": "he", "zh-CN": "zh", "zh-TW": "zh"}


def to_google(code: str) -> str:
    return _WHISPER_TO_GOOGLE.get(code, code)


def to_whisper(code: str) -> str:
    return _GOOGLE_TO_WHISPER.get(code, code.split("-")[0])


class SpeechRecognitionError(RuntimeError):
    """The audio could not be decoded or contained no speech; safe to show to users."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str              # Google Translate code ("es", "iw", "zh-CN", ...)
    language_probability: float
    duration: float            # seconds of audio
    seconds: float             # processing time
    segments: list[str] = field(default_factory=list)

    @property
    def real_time_factor(self) -> float:
        return self.seconds / self.duration if self.duration else 0.0


class Transcriber:
    def __init__(self, model_size: str = MODEL_SIZE, compute_type: str = "int8", cpu_threads: int = 4) -> None:
        from faster_whisper import WhisperModel

        self.model_size = model_size
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type, cpu_threads=cpu_threads)
        self._lock = threading.Lock()

    def transcribe(self, audio: Union[bytes, str, Path], language: Optional[str] = None,
                   task: str = "transcribe") -> Transcript:
        """``task="translate"`` makes Whisper itself output English (used as a comparison)."""
        source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else str(audio)
        start = time.perf_counter()
        try:
            with self._lock:
                segments, info = self._model.transcribe(
                    source, language=to_whisper(language) if language else None, task=task,
                    beam_size=5, vad_filter=True, condition_on_previous_text=False)
                parts = [s.text.strip() for s in segments]
        except Exception as exc:   # PyAV decode errors and friends
            raise SpeechRecognitionError("Couldn't read that audio. Try recording again.") from exc
        text = " ".join(p for p in parts if p)
        if not text:
            raise SpeechRecognitionError("I didn't hear any speech in that recording.")
        return Transcript(text, to_google(info.language), float(info.language_probability), float(info.duration),
                          time.perf_counter() - start, parts)


@lru_cache(maxsize=1)
def get_transcriber() -> Transcriber:
    return Transcriber()
