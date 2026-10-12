"""UI tests with Streamlit's AppTest; providers and TTS are faked (no network)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.conftest import FakeProvider
from translation_tool import service as service_mod
from translation_tool import speech as speech_mod
from translation_tool.providers import ProviderError

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def providers(monkeypatch):
    google = FakeProvider(name="Google")
    mymemory = FakeProvider(name="MyMemory", needs_source=True)
    monkeypatch.setattr(service_mod, "GoogleProvider", lambda: google)
    monkeypatch.setattr(service_mod, "MyMemoryProvider", lambda: mymemory)
    monkeypatch.setattr(speech_mod, "synthesize", lambda text, lang: b"ID3fake")
    st.cache_resource.clear()
    st.cache_data.clear()
    return google, mymemory


@pytest.fixture
def app(providers) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)


def translate(at, text, src=None, tgt=None):
    if src:
        at.selectbox(key="src").set_value(src)
    if tgt:
        at.selectbox(key="tgt").set_value(tgt)
    at.text_area(key="input_text").input(text)
    button(at, "Translate").click()
    at.run()
    assert not at.exception


def page_text(at):
    return " ".join(m.value for m in at.markdown)


def test_initial_state(app):
    assert app.selectbox(key="src").value == "auto"
    assert app.selectbox(key="tgt").value == "hi"
    assert app.session_state.result is None


def test_translate_shows_result_detection_and_history(app, providers):
    translate(app, "Bonjour tout le monde, comment allez-vous ?", tgt="en")
    text = page_text(app)
    assert "[en] Bonjour tout le monde" in text
    assert "Detected French" in text
    assert "via Google" in text
    assert len(app.session_state.history) == 1
    assert any("characters" in c.value for c in app.caption)


def test_line_breaks_are_rendered(app):
    translate(app, "Line one\n\nLine two", src="en", tgt="fr")
    assert "[fr] Line one<br><br>[fr] Line two" in page_text(app)


def test_output_is_html_escaped(app):
    translate(app, "<script>alert(1)</script>", src="en", tgt="fr")
    assert "&lt;script&gt;" in page_text(app)


def test_empty_input_warns(app, providers):
    button(app, "Translate").click()
    app.run()
    assert any("enter some text" in w.value for w in app.warning)
    assert providers[0].calls == []


def test_network_failure_shows_friendly_error(app, providers):
    google, mymemory = providers
    err = ProviderError("Google: network error", transient=True)
    google.errors = [err, err]
    mymemory.errors = [err, err]
    translate(app, "Hello there, my friend", src="en", tgt="fr")
    assert any("Check your internet connection" in e.value for e in app.error)
    assert app.session_state.result is None


def test_failover_is_visible(app, providers):
    google, _ = providers
    err = ProviderError("Google: rate limited", transient=True)
    google.errors = [err, err]
    translate(app, "Hello there, my friend", src="en", tgt="fr")
    assert "via MyMemory" in page_text(app)


def test_swap_languages_moves_translation_into_input(app):
    translate(app, "Hello there, my friend", src="en", tgt="fr")
    button(app, "⇄").click()
    app.run()
    assert app.selectbox(key="src").value == "fr"
    assert app.selectbox(key="tgt").value == "en"
    assert app.text_area(key="input_text").value == "[fr] Hello there, my friend"


def test_swap_with_auto_uses_detected_language(app):
    translate(app, "Bonjour tout le monde, comment allez-vous ?", tgt="en")
    button(app, "⇄").click()
    app.run()
    assert app.selectbox(key="src").value == "en"
    assert app.selectbox(key="tgt").value == "fr"


def test_swap_with_auto_and_no_translation_warns(app):
    button(app, "⇄").click()
    app.run()
    assert any("before swapping" in w.value for w in app.warning)
    assert app.selectbox(key="src").value == "auto"


def test_listen_and_cached_repeat(app, providers):
    translate(app, "Good morning everyone", src="en", tgt="fr")
    button(app, "🔊 Listen").click()
    app.run()
    assert app.session_state.audio == b"ID3fake"
    translate(app, "Good morning everyone", src="en", tgt="fr")
    assert "cached" in page_text(app)
    assert len(providers[0].calls) == 1


def test_history_restore_and_clear(app):
    translate(app, "First text to translate", src="en", tgt="fr")
    translate(app, "Second text to translate", src="en", tgt="de")
    assert [h["result"].target for h in app.session_state.history] == ["de", "fr"]
    next(b for b in app.button if b.label == "Use again" and b.key == "restore-1").click()
    app.run()
    assert app.text_area(key="input_text").value == "First text to translate"
    assert app.selectbox(key="tgt").value == "fr"
    app.button(key="clear_history").click()
    app.run()
    assert app.session_state.history == []


def test_clear_input(app):
    translate(app, "Some text", src="en", tgt="fr")
    app.button(key="clear_input").click()
    app.run()
    assert app.text_area(key="input_text").value == ""
    assert app.session_state.result is None
