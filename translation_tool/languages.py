"""Supported languages and offline source-language detection.

The language table ships with ``deep-translator`` (no network needed).
Codes follow Google Translate, e.g. ``"iw"`` for Hebrew and ``"zh-CN"``.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, LangDetectException, detect_langs

logger = logging.getLogger(__name__)

AUTO = "auto"

# langdetect is randomised by default; a fixed seed makes it deterministic.
DetectorFactory.seed = 0

#: langdetect code -> Google code, where they differ.
_DETECT_TO_GOOGLE: dict[str, str] = {"he": "iw", "zh-cn": "zh-CN", "zh-tw": "zh-TW"}

#: Below this probability a detection is not reported.
MIN_DETECTION_CONFIDENCE = 0.70


@lru_cache(maxsize=1)
def languages() -> dict[str, str]:
    """Map of language code -> display name (e.g. ``{"fr": "French"}``), sorted by name."""
    raw: dict[str, str] = GoogleTranslator().get_supported_languages(as_dict=True)
    by_code = {code: name.title() for name, code in raw.items()}
    return dict(sorted(by_code.items(), key=lambda kv: kv[1]))


def name_of(code: str | None) -> str:
    """Display name for *code* (``"Auto-detect"`` for ``auto``, the code itself if unknown)."""
    if code is None:
        return "Unknown"
    if code == AUTO:
        return "Auto-detect"
    return languages().get(code, code)


def is_supported(code: str, *, allow_auto: bool = False) -> bool:
    """Whether *code* is a known language code (optionally accepting ``auto``)."""
    return (allow_auto and code == AUTO) or code in languages()


def detect(text: str) -> tuple[str, float] | None:
    """Best-guess ``(google_code, probability)`` for *text*, or ``None``.

    Uses ``langdetect`` (offline, deterministic). Very short inputs are
    unreliable, so results under :data:`MIN_DETECTION_CONFIDENCE` are dropped.
    """
    if len(text.strip()) < 3:
        return None
    try:
        best = detect_langs(text)[0]
    except LangDetectException:
        return None
    code = _DETECT_TO_GOOGLE.get(best.lang, best.lang)
    if best.prob < MIN_DETECTION_CONFIDENCE or code not in languages():
        logger.debug("Detection discarded: %s (%.2f)", best.lang, best.prob)
        return None
    return code, float(best.prob)
