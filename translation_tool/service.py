"""Translation service: validation, provider failover, retries, timeouts, caching.

The Streamlit UI talks only to :class:`TranslationService`; everything that can
go wrong on the network ends up as a :class:`TranslationError` with a message
that is safe to show to the user.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from typing import Callable, Sequence

from . import config, languages
from .languages import AUTO
from .providers import (
    GoogleProvider,
    MyMemoryProvider,
    ProviderError,
    TranslationProvider,
    UnsupportedLanguageError,
)

logger = logging.getLogger(__name__)

Detector = Callable[[str], "tuple[str, float] | None"]

_SENTENCE_END = re.compile(r"(?<=[.!?。！？।])\s+")


class InputError(ValueError):
    """The request itself is invalid (empty text, too long, unknown language)."""


class TranslationError(RuntimeError):
    """Every provider failed. ``str(err)`` is a user-friendly explanation."""


@dataclass(frozen=True)
class Translation:
    """Result of one translation request."""

    source_text: str
    text: str
    source: str  #: requested source code, may be ``"auto"``
    target: str
    provider: str
    detected_source: str | None = None  #: best guess when ``source == "auto"``
    detection_confidence: float | None = None
    cached: bool = False

    @property
    def effective_source(self) -> str | None:
        """The concrete source language, if known."""
        return self.detected_source if self.source == AUTO else self.source


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split one line into pieces of at most *max_chars*, preferring sentence ends."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > max_chars:  # a single huge sentence: cut at a space
            cut = sentence.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].rstrip())
            sentence = sentence[cut:].lstrip()
        candidate = f"{current} {sentence}" if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


class TranslationService:
    """Translate text using an ordered list of providers.

    Args:
        providers: tried in order; the next one is used if a provider fails
            or cannot handle the language pair. Defaults to Google, then MyMemory.
        max_chars: input length limit.
        timeout: seconds allowed per provider request.
        retries: extra attempts per provider for transient errors.
        backoff: base delay between retries (multiplied by the attempt number).
        cache_size: number of results kept in the LRU cache (0 disables it).
        detector: function returning ``(code, probability)`` or ``None``.
        sleep: injectable for tests.
    """

    def __init__(
        self,
        providers: Sequence[TranslationProvider] | None = None,
        *,
        max_chars: int = config.MAX_CHARS,
        timeout: float = config.REQUEST_TIMEOUT_S,
        retries: int = config.RETRIES,
        backoff: float = config.RETRY_BACKOFF_S,
        cache_size: int = config.CACHE_SIZE,
        detector: Detector = languages.detect,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.providers: list[TranslationProvider] = (
            list(providers) if providers is not None else [GoogleProvider(), MyMemoryProvider()]
        )
        if not self.providers:
            raise ValueError("At least one provider is required")
        self.max_chars = max_chars
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.cache_size = cache_size
        self._detector = detector
        self._sleep = sleep
        self._cache: OrderedDict[tuple[str, str, str], Translation] = OrderedDict()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")

    # ------------------------------------------------------------ validation

    def validate(self, text: str, source: str, target: str) -> str:
        """Return the cleaned text or raise :class:`InputError`."""
        if not isinstance(text, str) or not text.strip():
            raise InputError("Please enter some text to translate.")
        if len(text) > self.max_chars:
            raise InputError(
                f"Text is {len(text):,} characters; the limit is {self.max_chars:,}."
            )
        if not languages.is_supported(source, allow_auto=True):
            raise InputError(f"Unsupported source language: {source!r}")
        if not languages.is_supported(target):
            raise InputError(f"Unsupported target language: {target!r}")
        # Keep line structure, drop trailing whitespace and surrounding blank lines.
        return "\n".join(line.rstrip() for line in text.strip("\n").splitlines()).strip()

    # ------------------------------------------------------------ public API

    def translate(self, text: str, source: str = AUTO, target: str = config.DEFAULT_TARGET) -> Translation:
        """Translate *text* from *source* (or ``"auto"``) to *target*.

        Raises:
            InputError: invalid request.
            TranslationError: every provider failed.
        """
        text = self.validate(text, source, target)
        key = (text, source, target)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                logger.info("cache hit %s->%s (%d chars)", source, target, len(text))
                return replace(hit, cached=True)

        detected = self._detector(text) if source == AUTO else None
        detected_code, confidence = detected if detected else (None, None)

        if source != AUTO and source == target:
            result = Translation(text, text, source, target, provider="none")
        else:
            result = self._translate_with_failover(text, source, target, detected_code)
            result = replace(result, detected_source=detected_code, detection_confidence=confidence)

        with self._lock:
            self._cache[key] = result
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------ internals

    def _translate_with_failover(
        self, text: str, source: str, target: str, detected: str | None
    ) -> Translation:
        failures: list[ProviderError] = []
        for provider in self.providers:
            src = source
            if provider.needs_source and source == AUTO:
                if detected is None:
                    logger.info("%s skipped: source language unknown", provider.name)
                    continue
                src = detected
            try:
                translated = self._translate_lines(provider, text, src, target)
            except UnsupportedLanguageError as exc:
                logger.info("%s skipped: %s", provider.name, exc)
                continue
            except ProviderError as exc:
                logger.warning("%s failed: %s", provider.name, exc)
                failures.append(exc)
                continue
            logger.info("translated %s->%s with %s (%d chars)", source, target, provider.name, len(text))
            return Translation(text, translated, source, target, provider=provider.name)

        if not failures:
            raise TranslationError(
                "No available translation service supports this language pair. "
                "Try choosing the source language instead of auto-detect."
            )
        if all(f.transient for f in failures):
            raise TranslationError(
                "Couldn't reach the translation service (network problem or rate limit). "
                "Check your internet connection and try again in a moment."
            )
        raise TranslationError("Translation failed: " + "; ".join(str(f) for f in failures))

    def _translate_lines(self, provider: TranslationProvider, text: str, source: str, target: str) -> str:
        """Translate line by line so paragraph breaks survive the round trip."""
        done: dict[str, str] = {}
        out_lines = []
        for line in text.split("\n"):
            if not line.strip():
                out_lines.append("")
                continue
            parts = []
            for chunk in chunk_text(line, provider.max_chars):
                if chunk not in done:
                    done[chunk] = self._call(provider, chunk, source, target)
                parts.append(done[chunk])
            out_lines.append(" ".join(parts))
        return "\n".join(out_lines)

    def _call(self, provider: TranslationProvider, text: str, source: str, target: str) -> str:
        """One request with a timeout, retrying transient failures."""
        for attempt in range(self.retries + 1):
            future = self._pool.submit(provider.translate, text, source, target)
            try:
                return future.result(timeout=self.timeout)
            except FutureTimeout:
                future.cancel()
                error = ProviderError(f"{provider.name}: timed out after {self.timeout:g}s", transient=True)
            except ProviderError as exc:
                error = exc
            if not error.transient or attempt == self.retries:
                raise error
            delay = self.backoff * (attempt + 1)
            logger.info("%s (attempt %d), retrying in %.2fs", error, attempt + 1, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover
