"""Translation back-ends behind one small interface.

Each provider turns third-party exceptions into :class:`ProviderError`, so
the service layer can decide whether to retry, fail over, or give up without
knowing anything about the underlying library.
"""

from __future__ import annotations

import html
import logging
from typing import Callable, Protocol

import requests
from deep_translator import GoogleTranslator, MyMemoryTranslator
from deep_translator import exceptions as dt_exc

from .languages import AUTO, languages

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """A provider failed. ``transient`` errors are worth retrying."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class UnsupportedLanguageError(ProviderError):
    """The provider cannot handle this language pair (try the next provider)."""


class TranslationProvider(Protocol):
    """What the service needs from a translation back-end."""

    #: Short name shown in the UI ("Google", "MyMemory").
    name: str
    #: Longest text accepted in one request.
    max_chars: int
    #: ``True`` if the provider needs a concrete source language (no ``auto``).
    needs_source: bool

    def translate(self, text: str, source: str, target: str) -> str:
        """Translate *text*; raise :class:`ProviderError` on failure."""


def _wrap_library_errors(provider: str, call: Callable[[], str | None]) -> str:
    """Run *call* and normalise every failure into :class:`ProviderError`."""
    try:
        result = call()
    except (dt_exc.TooManyRequests,) as exc:
        raise ProviderError(f"{provider}: rate limited", transient=True) from exc
    except (dt_exc.RequestError, requests.RequestException) as exc:
        raise ProviderError(f"{provider}: network error ({exc})", transient=True) from exc
    except (dt_exc.LanguageNotSupportedException, dt_exc.InvalidSourceOrTargetLanguage) as exc:
        raise UnsupportedLanguageError(f"{provider}: language not supported") from exc
    except dt_exc.BaseError as exc:  # TranslationNotFound, NotValidLength, ...
        raise ProviderError(f"{provider}: {exc.message}") from exc
    except Exception as exc:  # noqa: BLE001 - malformed responses (bad JSON, missing keys)
        logger.exception("Unexpected %s failure", provider)
        raise ProviderError(f"{provider}: unexpected response") from exc
    if not isinstance(result, str) or not result.strip():
        raise ProviderError(f"{provider}: empty response")
    return result


class GoogleProvider:
    """Google Translate's free web endpoint via ``deep-translator``."""

    name = "Google"
    max_chars = 4999  # deep-translator rejects len >= 5000
    needs_source = False

    def __init__(self, client_factory: Callable[..., GoogleTranslator] = GoogleTranslator) -> None:
        self._client_factory = client_factory

    def translate(self, text: str, source: str, target: str) -> str:
        return _wrap_library_errors(
            self.name,
            lambda: self._client_factory(source=source, target=target).translate(text),
        )


class MyMemoryProvider:
    """MyMemory's free API via ``deep-translator`` - used as a fallback.

    MyMemory needs an explicit source language and uses regional codes
    (``en-GB``), so Google-style codes are mapped by language name.
    """

    name = "MyMemory"
    max_chars = 499
    needs_source = True

    #: Explicit mappings where the language names differ between the services.
    _OVERRIDES = {"iw": "he-IL", "jw": "jv-ID", "tl": "tl-PH", "zh-CN": "zh-CN", "zh-TW": "zh-TW"}

    #: MyMemory reports some failures as "translations" in upper case.
    _ERROR_MARKERS = ("INVALID SOURCE LANGUAGE", "INVALID TARGET LANGUAGE", "MYMEMORY WARNING",
                      "QUERY LENGTH LIMIT", "PLEASE SELECT TWO DISTINCT LANGUAGES")

    def __init__(
        self, client_factory: Callable[..., MyMemoryTranslator] = MyMemoryTranslator
    ) -> None:
        self._client_factory = client_factory
        self._codes = self._build_code_map()

    @classmethod
    def _build_code_map(cls) -> dict[str, str]:
        from deep_translator.constants import MY_MEMORY_LANGUAGES_TO_CODES as mm

        mapping: dict[str, str] = {}
        for code, name in languages().items():
            if code in cls._OVERRIDES:
                mapping[code] = cls._OVERRIDES[code]
            elif name.lower() in mm:
                mapping[code] = mm[name.lower()]
            else:
                prefixed = sorted(v for v in mm.values() if v.split("-")[0] == code)
                if prefixed:
                    mapping[code] = prefixed[0]
        return mapping

    def code_for(self, code: str) -> str | None:
        """MyMemory code for a Google-style *code* (``None`` if unsupported)."""
        return self._codes.get(code)

    def translate(self, text: str, source: str, target: str) -> str:
        if source == AUTO:
            raise UnsupportedLanguageError(f"{self.name}: needs an explicit source language")
        src, tgt = self.code_for(source), self.code_for(target)
        if src is None or tgt is None:
            raise UnsupportedLanguageError(f"{self.name}: language not supported")
        result = _wrap_library_errors(
            self.name, lambda: self._client_factory(source=src, target=tgt).translate(text)
        )
        if any(marker in result.upper() for marker in self._ERROR_MARKERS):
            raise ProviderError(f"{self.name}: {result[:120]}", transient="WARNING" in result.upper())
        return html.unescape(result)  # MyMemory returns HTML entities such as &#39;
