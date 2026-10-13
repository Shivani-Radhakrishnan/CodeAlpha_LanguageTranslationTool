"""Speech-to-speech translation: speech -> Whisper transcript -> translation -> spoken audio."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .asr import Transcriber, Transcript
from .service import Translation, TranslationService


@dataclass(frozen=True)
class SpokenTranslation:
    transcript: Transcript
    translation: Translation
    audio: Optional[bytes]          # MP3 of the translation, or None if no voice for the target


def speech_to_speech(audio: bytes, target: str, transcriber: Transcriber, service: TranslationService,
                     synthesize: Callable[[str, str], Optional[bytes]]) -> SpokenTranslation:
    """``synthesize(text, lang)`` returns MP3 bytes (``translation_tool.speech.synthesize``)."""
    heard = transcriber.transcribe(audio)
    translated = service.translate(heard.text, source=heard.language, target=target)
    return SpokenTranslation(heard, translated, synthesize(translated.text, target))
