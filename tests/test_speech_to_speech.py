"""Speech recognition wrapper and the speech-to-speech pipeline, with Whisper faked."""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("faster_whisper")

from translation_tool import asr
from translation_tool.asr import SpeechRecognitionError, Transcriber, to_google, to_whisper
from translation_tool.voice import speech_to_speech
from tests.conftest import FakeProvider
from tests.test_service import make


class FakeWhisper:
    """Stands in for faster_whisper.WhisperModel."""

    def __init__(self, *args, text=("Hola,", "¿dónde está la estación?"), language="es", **kwargs):
        self.text, self.language, self.calls = text, language, []

    def transcribe(self, source, **kwargs):
        self.calls.append(kwargs)
        if source == "broken":
            raise ValueError("Invalid data found when processing input")
        segments = (SimpleNamespace(text=f" {t}") for t in self.text)
        return segments, SimpleNamespace(language=self.language, language_probability=0.98, duration=4.0)


@pytest.fixture
def transcriber(monkeypatch):
    def make_transcriber(**fake_kwargs):
        fake = FakeWhisper(**fake_kwargs)
        import faster_whisper

        monkeypatch.setattr(faster_whisper, "WhisperModel", lambda *a, **k: fake)
        return Transcriber(), fake
    return make_transcriber


def test_language_codes_map_between_whisper_and_google():
    assert to_google("he") == "iw" and to_google("zh") == "zh-CN" and to_google("es") == "es"
    assert to_whisper("iw") == "he" and to_whisper("zh-TW") == "zh" and to_whisper("pt-BR") == "pt"


def test_transcript_joins_segments_and_reports_language(transcriber):
    t, fake = transcriber()
    out = t.transcribe(b"RIFF....")
    assert out.text == "Hola, ¿dónde está la estación?" and out.language == "es"
    assert out.language_probability == pytest.approx(0.98) and out.duration == 4.0
    assert fake.calls[0]["vad_filter"] and fake.calls[0]["language"] is None


def test_hebrew_is_reported_with_googles_code(transcriber):
    t, _ = transcriber(text=("שלום",), language="he")
    assert t.transcribe(b"x").language == "iw"


def test_silence_and_unreadable_audio_raise_friendly_errors(transcriber):
    t, _ = transcriber(text=("", " "))
    with pytest.raises(SpeechRecognitionError, match="didn't hear"):
        t.transcribe(b"x")
    with pytest.raises(SpeechRecognitionError, match="Couldn't read"):
        t.transcribe("broken")


def test_speech_to_speech_uses_the_detected_language(transcriber):
    t, _ = transcriber()
    provider = FakeProvider()
    service = make(provider)
    spoken = []
    result = speech_to_speech(b"x", "en", t, service, lambda text, lang: spoken.append((text, lang)) or b"mp3")
    assert result.translation.source == "es" and result.translation.target == "en"
    assert result.audio == b"mp3" and spoken == [(result.translation.text, "en")]


def test_published_speech_results_reproduce_from_recorded_outputs():
    """Recomputes WER, language ID and chrF from data/speech_outputs.json (no audio or model)."""
    pytest.importorskip("jiwer")
    pytest.importorskip("sacrebleu")
    from eval import speech_eval

    published = json.loads(speech_eval.RESULTS.read_text(encoding="utf-8"))
    rows = speech_eval.load_manifest()
    outputs = json.loads(speech_eval.OUTPUTS.read_text(encoding="utf-8"))
    now = speech_eval.compute(rows, outputs)
    assert now["asr"] == published["asr"]
    assert now["translation"] == published["translation"]


def test_wer_normalisation():
    from eval.speech_eval import normalise

    assert normalise("Hello, World!  It's") == "hello world it s"
    assert normalise("¿Dónde está?") == "dónde está"
