import pytest
import requests
from gtts import gTTSError

from translation_tool import speech


class FakeTTS:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        FakeTTS.calls.append(kwargs)
        self.kwargs = kwargs

    def write_to_fp(self, fp):
        fp.write(b"ID3fake-mp3")


def failing(exc):
    class Failing(FakeTTS):
        def write_to_fp(self, fp):
            raise exc

    return Failing


@pytest.mark.parametrize("code, expected", [("en", "en"), ("zh-CN", "zh-CN"), ("iw", "iw"), ("pt", "pt"), ("hy", None), ("mni-Mtei", None)])
def test_tts_code(code, expected):
    assert speech.tts_code(code) == expected


def test_synthesize_returns_mp3_bytes():
    FakeTTS.calls.clear()
    audio = speech.synthesize("  Bonjour  ", "fr", timeout=3, engine=FakeTTS)
    assert audio == b"ID3fake-mp3"
    assert FakeTTS.calls == [{"text": "Bonjour", "lang": "fr", "timeout": 3}]


def test_synthesize_truncates_long_text():
    FakeTTS.calls.clear()
    speech.synthesize("a" * 5000, "en", engine=FakeTTS)
    assert len(FakeTTS.calls[0]["text"]) == speech.MAX_TTS_CHARS


def test_unsupported_language():
    with pytest.raises(speech.SpeechError, match="isn't available"):
        speech.synthesize("Barev", "hy", engine=FakeTTS)


def test_empty_text():
    with pytest.raises(speech.SpeechError, match="Nothing"):
        speech.synthesize("   ", "en", engine=FakeTTS)


@pytest.mark.parametrize("exc", [gTTSError("429"), requests.ConnectionError("offline")])
def test_network_errors_become_speech_errors(exc):
    with pytest.raises(speech.SpeechError, match="Couldn't generate audio"):
        speech.synthesize("hello", "en", engine=failing(exc))
