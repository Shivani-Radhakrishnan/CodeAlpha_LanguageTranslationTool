import pytest

from translation_tool.service import (
    InputError,
    TranslationError,
    TranslationService,
    chunk_text,
)
from translation_tool.providers import ProviderError
from tests.conftest import FakeProvider


def make(*providers, **kwargs):
    kwargs.setdefault("sleep", lambda s: None)
    kwargs.setdefault("detector", lambda text: ("en", 0.99))
    return TranslationService(list(providers), **kwargs)


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty_text_rejected(fake, text):
    with pytest.raises(InputError, match="enter some text"):
        make(fake).translate(text, "auto", "fr")
    assert fake.calls == []


def test_too_long_text_rejected(fake):
    service = make(fake, max_chars=10)
    with pytest.raises(InputError, match="limit is 10"):
        service.translate("x" * 11, "auto", "fr")
    assert service.translate("x" * 10, "auto", "fr").text == "[fr] " + "x" * 10


@pytest.mark.parametrize("source, target", [("xx", "fr"), ("en", "auto"), ("en", "klingon")])
def test_unknown_languages_rejected(fake, source, target):
    with pytest.raises(InputError, match="Unsupported"):
        make(fake).translate("hello", source, target)


# ---------------------------------------------------------------- happy path


def test_translates_and_reports_detection(fake):
    result = make(fake, detector=lambda t: ("es", 0.97)).translate("hola", "auto", "en")
    assert result.text == "[en] hola"
    assert result.provider == "Fake"
    assert result.detected_source == "es"
    assert result.detection_confidence == 0.97
    assert result.effective_source == "es"
    assert fake.calls == [("hola", "auto", "en")]


def test_explicit_source_skips_detection(fake):
    def boom(text):
        raise AssertionError("detector should not run")

    result = make(fake, detector=boom).translate("hello", "en", "de")
    assert result.detected_source is None
    assert result.effective_source == "en"


def test_same_source_and_target_needs_no_request(fake):
    result = make(fake).translate("hello", "en", "en")
    assert result.text == "hello"
    assert result.provider == "none"
    assert fake.calls == []


def test_line_breaks_are_preserved(fake):
    result = make(fake).translate("first line\n\nsecond line\n", "en", "fr")
    assert result.text == "[fr] first line\n\n[fr] second line"


def test_long_lines_are_chunked_to_provider_limit():
    small = FakeProvider(max_chars=20)
    text = "One sentence here. Another one here. And a third."
    make(small).translate(text, "en", "fr")
    assert all(len(call[0]) <= 20 for call in small.calls)
    assert " ".join(call[0] for call in small.calls) == text


def test_repeated_lines_translated_once(fake):
    make(fake).translate("hi\nhi\nhi", "en", "fr")
    assert len(fake.calls) == 1


# ---------------------------------------------------------------- caching


def test_cache_returns_same_result_without_new_request(fake):
    service = make(fake)
    first = service.translate("hello", "auto", "fr")
    second = service.translate("hello", "auto", "fr")
    assert not first.cached and second.cached
    assert second.text == first.text
    assert len(fake.calls) == 1


def test_cache_key_includes_languages(fake):
    service = make(fake)
    service.translate("hello", "auto", "fr")
    service.translate("hello", "auto", "de")
    assert len(fake.calls) == 2


def test_cache_is_bounded_lru(fake):
    service = make(fake, cache_size=2)
    for word in ["a1", "b1", "c1"]:
        service.translate(word, "en", "fr")
    service.translate("a1", "en", "fr")  # evicted -> new request
    assert len(fake.calls) == 4


def test_failures_are_not_cached(fake, transient):
    fake.errors = [transient, transient]
    service = make(fake, retries=1)
    with pytest.raises(TranslationError):
        service.translate("hello", "en", "fr")
    assert service.translate("hello", "en", "fr").text == "[fr] hello"


# ---------------------------------------------------------------- retries & failover


def test_transient_error_is_retried_with_backoff(fake, transient):
    sleeps = []
    fake.errors = [transient]
    result = make(fake, retries=1, backoff=0.5, sleep=sleeps.append).translate("hi", "en", "fr")
    assert result.text == "[fr] hi"
    assert len(fake.calls) == 2
    assert sleeps == [0.5]


def test_permanent_error_is_not_retried(fake):
    fake.errors = [ProviderError("Fake: bad response")]
    with pytest.raises(TranslationError, match="bad response"):
        make(fake, retries=3).translate("hi", "en", "fr")
    assert len(fake.calls) == 1


def test_fails_over_to_next_provider(transient):
    primary = FakeProvider(name="Primary", errors=[transient, transient])
    backup = FakeProvider(name="Backup")
    result = make(primary, backup, retries=1).translate("hi", "en", "fr")
    assert result.provider == "Backup"
    assert len(primary.calls) == 2


def test_unsupported_language_skips_provider_without_retry(unsupported):
    primary = FakeProvider(name="Primary", errors=[unsupported])
    backup = FakeProvider(name="Backup")
    assert make(primary, backup, retries=3).translate("hi", "en", "fr").provider == "Backup"
    assert len(primary.calls) == 1


def test_provider_needing_source_uses_detected_language(transient):
    primary = FakeProvider(name="Primary", errors=[transient, transient])
    backup = FakeProvider(name="Backup", needs_source=True)
    make(primary, backup, detector=lambda t: ("es", 0.9)).translate("hola", "auto", "en")
    assert backup.calls == [("hola", "es", "en")]


def test_provider_needing_source_skipped_when_detection_fails(transient):
    primary = FakeProvider(name="Primary", errors=[transient, transient])
    backup = FakeProvider(name="Backup", needs_source=True)
    with pytest.raises(TranslationError, match="Couldn't reach"):
        make(primary, backup, detector=lambda t: None).translate("hola", "auto", "en")
    assert backup.calls == []


def test_network_failure_gives_friendly_message(transient):
    a = FakeProvider(name="A", errors=[transient] * 2)
    b = FakeProvider(name="B", errors=[transient] * 2)
    with pytest.raises(TranslationError, match="Check your internet connection"):
        make(a, b).translate("hi", "en", "fr")


def test_no_provider_supports_pair(unsupported):
    p = FakeProvider(errors=[unsupported])
    with pytest.raises(TranslationError, match="No available translation service"):
        make(p).translate("hi", "en", "fr")


def test_timeout_is_enforced_and_retried():
    slow = FakeProvider(name="Slow", delay=0.5)
    backup = FakeProvider(name="Backup")
    result = make(slow, backup, timeout=0.05, retries=1).translate("hi", "en", "fr")
    assert result.provider == "Backup"
    assert len(slow.calls) == 2


def test_requires_a_provider():
    with pytest.raises(ValueError):
        TranslationService([])


def test_default_providers_are_google_then_mymemory():
    assert [p.name for p in TranslationService().providers] == ["Google", "MyMemory"]


# ---------------------------------------------------------------- chunking


def test_chunk_text_short_is_untouched():
    assert chunk_text("hello", 10) == ["hello"]


def test_chunk_text_prefers_sentence_boundaries():
    assert chunk_text("Aaa bbb. Ccc ddd. Eee.", 10) == ["Aaa bbb.", "Ccc ddd.", "Eee."]


def test_chunk_text_splits_long_sentence_on_spaces():
    chunks = chunk_text("word " * 30, 12)
    assert all(len(c) <= 12 for c in chunks)
    assert " ".join(chunks).split() == ["word"] * 30


def test_chunk_text_hard_splits_unbroken_text():
    assert chunk_text("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]
