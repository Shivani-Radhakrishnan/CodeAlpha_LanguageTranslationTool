"""Text-to-speech with gTTS, returned as MP3 bytes for ``st.audio``.

gTTS calls Google's TTS web endpoint and produces an MP3 that the *browser*
plays. The previous ``pyttsx3`` approach spoke through the *server's* sound
card, which does nothing for a remote user and fails on headless machines.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Callable

from gtts import gTTS, gTTSError
from gtts.lang import tts_langs

from . import config

logger = logging.getLogger(__name__)

#: Characters spoken at most (keeps requests and audio size reasonable).
MAX_TTS_CHARS = 1000


class SpeechError(RuntimeError):
    """Speech synthesis failed; the message is safe to show to users."""


@lru_cache(maxsize=1)
def _voices() -> dict[str, str]:
    return tts_langs()


def tts_code(lang: str) -> str | None:
    """gTTS voice code for a translation language code, or ``None`` if unsupported.

    Google Translate and gTTS share codes (``iw``, ``zh-CN``, ...); regional
    variants fall back to the base language.
    """
    if lang in _voices():
        return lang
    base = lang.split("-")[0]
    return base if base in _voices() else None


def synthesize(
    text: str,
    lang: str,
    *,
    timeout: float = config.TTS_TIMEOUT_S,
    engine: Callable[..., gTTS] = gTTS,
) -> bytes:
    """Return MP3 audio of *text* spoken in *lang*.

    Raises:
        SpeechError: unsupported language, empty text or a network failure.
    """
    code = tts_code(lang)
    if code is None:
        raise SpeechError("Text-to-speech isn't available for this language.")
    text = text.strip()[:MAX_TTS_CHARS]
    if not text:
        raise SpeechError("Nothing to read aloud.")
    buffer = io.BytesIO()
    try:
        engine(text=text, lang=code, timeout=timeout).write_to_fp(buffer)
    except (gTTSError, OSError) as exc:  # requests errors subclass OSError
        logger.warning("TTS failed for %s: %s", code, exc)
        raise SpeechError("Couldn't generate audio right now. Please try again.") from exc
    return buffer.getvalue()
