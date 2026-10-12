import pytest

from translation_tool import languages as L


def test_language_table():
    langs = L.languages()
    assert len(langs) > 100
    assert langs["fr"] == "French" and langs["iw"] == "Hebrew"
    assert list(langs.values()) == sorted(langs.values())


def test_name_of():
    assert L.name_of("auto") == "Auto-detect"
    assert L.name_of("de") == "German"
    assert L.name_of("xx") == "xx"
    assert L.name_of(None) == "Unknown"


def test_is_supported():
    assert L.is_supported("es")
    assert not L.is_supported("auto")
    assert L.is_supported("auto", allow_auto=True)
    assert not L.is_supported("klingon")


@pytest.mark.parametrize(
    "text, code",
    [
        ("Bonjour tout le monde, comment allez-vous aujourd'hui ?", "fr"),
        ("¿Dónde está la biblioteca más cercana, por favor?", "es"),
        ("שלום, מה שלומך היום?", "iw"),  # langdetect says "he"; Google uses "iw"
        ("今天天气很好，我们去公园散步吧。", "zh-CN"),
    ],
)
def test_detect(text, code):
    detected = L.detect(text)
    assert detected is not None
    assert detected[0] == code
    assert 0.7 <= detected[1] <= 1.0


@pytest.mark.parametrize("text", ["", "  ", "ok", "12345 67890"])
def test_detect_returns_none_when_unsure(text):
    assert L.detect(text) is None


def test_detect_is_deterministic():
    text = "Das ist ein kurzer deutscher Satz."
    assert len({L.detect(text) for _ in range(5)}) == 1
