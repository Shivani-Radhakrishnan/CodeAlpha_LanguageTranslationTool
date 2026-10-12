import pytest
import requests
from deep_translator import exceptions as dt_exc

from translation_tool.providers import (
    GoogleProvider,
    MyMemoryProvider,
    ProviderError,
    UnsupportedLanguageError,
)


class FakeClient:
    """Stands in for a deep-translator class: records init args, returns/raises."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def translate(self, text):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


# ---------------------------------------------------------------- Google


def test_google_success_passes_languages():
    client = FakeClient("Bonjour")
    assert GoogleProvider(client).translate("Hello", "auto", "fr") == "Bonjour"
    assert client.kwargs == {"source": "auto", "target": "fr"}


@pytest.mark.parametrize(
    "error, transient",
    [
        (dt_exc.TooManyRequests(), True),
        (dt_exc.RequestError(), True),
        (requests.ConnectionError("offline"), True),
        (requests.Timeout("slow"), True),
        (dt_exc.TranslationNotFound("x"), False),
        (ValueError("bad json"), False),
    ],
)
def test_google_errors_are_normalised(error, transient):
    with pytest.raises(ProviderError) as info:
        GoogleProvider(FakeClient(error)).translate("Hello", "auto", "fr")
    assert info.value.transient is transient


def test_google_unsupported_language():
    err = dt_exc.LanguageNotSupportedException("xx")
    with pytest.raises(UnsupportedLanguageError):
        GoogleProvider(FakeClient(err)).translate("Hello", "xx", "fr")


@pytest.mark.parametrize("outcome", [None, "", "   "])
def test_google_empty_response_is_an_error(outcome):
    with pytest.raises(ProviderError, match="empty"):
        GoogleProvider(FakeClient(outcome)).translate("Hello", "auto", "fr")


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def close(self):
        pass


def test_google_parses_real_library_response(monkeypatch):
    """Exercise the real deep-translator code with the HTTP call mocked."""
    seen = {}

    def fake_get(url, params=None, **kwargs):
        seen.update(params)
        return FakeResponse(200, '<html><div class="t0">Hallo Welt</div></html>')

    monkeypatch.setattr("deep_translator.google.requests.get", fake_get)
    assert GoogleProvider().translate("Hello world", "en", "de") == "Hallo Welt"
    assert seen["sl"] == "en" and seen["tl"] == "de" and seen["q"] == "Hello world"


def test_google_http_429_is_transient(monkeypatch):
    monkeypatch.setattr(
        "deep_translator.google.requests.get", lambda *a, **k: FakeResponse(429)
    )
    with pytest.raises(ProviderError) as info:
        GoogleProvider().translate("Hello", "en", "de")
    assert info.value.transient


# ---------------------------------------------------------------- MyMemory


@pytest.mark.parametrize(
    "code, expected",
    [("en", "en-GB"), ("fr", "fr-FR"), ("de", "de-DE"), ("hi", "hi-IN"), ("iw", "he-IL"), ("zh-CN", "zh-CN")],
)
def test_mymemory_code_mapping(code, expected):
    assert MyMemoryProvider(FakeClient("x")).code_for(code) == expected


def test_mymemory_needs_explicit_source():
    client = FakeClient("x")
    with pytest.raises(UnsupportedLanguageError):
        MyMemoryProvider(client).translate("Hello", "auto", "fr")
    assert client.kwargs is None  # no request attempted


def test_mymemory_success_unescapes_html():
    client = FakeClient("C&#39;est bon")
    assert MyMemoryProvider(client).translate("It's good", "en", "fr") == "C'est bon"
    assert client.kwargs == {"source": "en-GB", "target": "fr-FR"}


@pytest.mark.parametrize(
    "message, transient",
    [
        ("'AUTO' IS AN INVALID SOURCE LANGUAGE . EXAMPLE: LANGPAIR=EN|IT", False),
        ("MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY", True),
    ],
)
def test_mymemory_error_text_is_detected(message, transient):
    with pytest.raises(ProviderError) as info:
        MyMemoryProvider(FakeClient(message)).translate("Hello", "en", "fr")
    assert info.value.transient is transient
