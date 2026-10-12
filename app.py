"""Streamlit UI for the Language Translation Tool.

Run with:  streamlit run app.py

All translation, detection and speech logic lives in :mod:`translation_tool`;
this file only handles layout and session state.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime

import streamlit as st

from translation_tool import config
from translation_tool.languages import AUTO, languages, name_of
from translation_tool.service import InputError, Translation, TranslationError, TranslationService
from translation_tool.speech import SpeechError, synthesize, tts_code

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("translation_tool.app")

st.set_page_config(page_title="Language Translator", page_icon="🌐", layout="centered")

CSS = """
<style>
.result {
    font-size: 1.15rem;
    line-height: 1.6;
    padding: 0.25rem 0;
}
.meta { font-size: 0.85rem; opacity: 0.75; }
</style>
"""


# ---------------------------------------------------------------- resources


@st.cache_resource
def get_service() -> TranslationService:
    """One service (and translation cache) shared by all sessions."""
    return TranslationService()


@st.cache_data(show_spinner=False, max_entries=64)
def speak(text: str, lang: str) -> bytes:
    """Cached text-to-speech so replaying a translation costs no request."""
    return synthesize(text, lang)


# ---------------------------------------------------------------- state & callbacks


def init_state() -> None:
    defaults = {
        "src": config.DEFAULT_SOURCE,
        "tgt": config.DEFAULT_TARGET,
        "input_text": "",
        "result": None,
        "audio": None,
        "history": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def swap_languages() -> None:
    """Swap source/target and move the translation into the input box."""
    result: Translation | None = st.session_state.result
    src = st.session_state.src
    if src == AUTO:
        src = result.effective_source if result else None
        if src is None:
            st.session_state.flash = "Pick a source language (or translate once) before swapping."
            return
    st.session_state.src, st.session_state.tgt = st.session_state.tgt, src
    if result is not None:
        st.session_state.input_text = result.text
    st.session_state.result = None
    st.session_state.audio = None


def clear_input() -> None:
    st.session_state.input_text = ""
    st.session_state.result = None
    st.session_state.audio = None


def run_translation() -> None:
    text = st.session_state.input_text
    try:
        result = get_service().translate(text, st.session_state.src, st.session_state.tgt)
    except InputError as exc:
        st.session_state.flash = str(exc)
        return
    except TranslationError as exc:
        st.session_state.error = str(exc)
        return
    st.session_state.result = result
    st.session_state.audio = None
    history = st.session_state.history
    history.insert(0, {"time": datetime.now().strftime("%H:%M"), "result": result})
    del history[config.HISTORY_SIZE :]


def restore(index: int) -> None:
    item = st.session_state.history[index]["result"]
    st.session_state.src, st.session_state.tgt = item.source, item.target
    st.session_state.input_text = item.source_text
    st.session_state.result = item
    st.session_state.audio = None


def clear_history() -> None:
    st.session_state.history = []


# ---------------------------------------------------------------- rendering


def as_html(text: str) -> str:
    """Escape *text* for safe HTML display, keeping its line breaks."""
    return html.escape(text).replace("\n", "<br>")


def render_result(result: Translation) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="result">{as_html(result.text)}</div>', unsafe_allow_html=True)
        if result.source != AUTO:
            direction = f"{name_of(result.source)} → {name_of(result.target)}"
        elif result.detected_source:
            direction = (
                f"Detected {name_of(result.detected_source)} "
                f"({result.detection_confidence:.0%}) → {name_of(result.target)}"
            )
        else:
            direction = f"Auto-detected by the service → {name_of(result.target)}"
        meta = [direction, f"via {result.provider}"]
        if result.cached:
            meta.append("cached")
        st.markdown(f'<span class="meta">{" · ".join(meta)}</span>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Download .txt",
        data=result.text.encode("utf-8"),
        file_name=f"translation_{result.target}.txt",
        mime="text/plain",
        use_container_width=True,
    )
    can_speak = tts_code(result.target) is not None
    if c2.button(
        "🔊 Listen",
        disabled=not can_speak,
        help=None if can_speak else "Text-to-speech isn't available for this language",
        use_container_width=True,
    ):
        try:
            with st.spinner("Generating audio..."):
                st.session_state.audio = speak(result.text, result.target)
        except SpeechError as exc:
            st.warning(str(exc))
    if st.session_state.audio:
        st.audio(st.session_state.audio, format="audio/mp3")
    with st.expander("Copy text"):
        st.code(result.text, language=None, wrap_lines=True)


def render_history() -> None:
    history = st.session_state.history
    if not history:
        return
    head, action = st.columns([4, 1])
    head.markdown("#### 🕘 History")
    action.button("Clear", key="clear_history", on_click=clear_history, use_container_width=True)
    for i, item in enumerate(history):
        r: Translation = item["result"]
        preview = r.source_text if len(r.source_text) <= 40 else r.source_text[:40] + "…"
        label = f"{item['time']} · {name_of(r.effective_source or AUTO)} → {name_of(r.target)} · {preview}"
        with st.expander(label):
            st.markdown(f'<div class="result">{as_html(r.text)}</div>', unsafe_allow_html=True)
            st.button("Use again", key=f"restore-{i}", on_click=restore, args=(i,))


def render_sidebar(service: TranslationService) -> None:
    with st.sidebar:
        st.markdown("### About")
        st.markdown(
            "Translates between 100+ languages using free web translation services, "
            f"tried in order: **{' → '.join(p.name for p in service.providers)}**."
        )
        st.markdown(
            f"- Up to {config.MAX_CHARS:,} characters\n"
            f"- {config.RETRIES} retry and {config.REQUEST_TIMEOUT_S:g}s timeout per request\n"
            "- Repeated translations are served from a cache\n"
            "- Auto-detect is a best guess for short text"
        )


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()
    service = get_service()
    render_sidebar(service)

    st.markdown("## 🌐 Language Translation Tool")
    st.caption("Auto-detect, swap languages, listen, download, and keep a history of your translations.")

    codes = list(languages())
    left, mid, right = st.columns([5, 1, 5], vertical_alignment="bottom")
    left.selectbox("From", [AUTO, *codes], key="src", format_func=name_of)
    mid.button("⇄", on_click=swap_languages, help="Swap languages", use_container_width=True)
    right.selectbox("To", codes, key="tgt", format_func=name_of)

    st.text_area(
        "Text to translate",
        key="input_text",
        height=180,
        max_chars=config.MAX_CHARS,
        placeholder="Type or paste text here…",
    )
    n = len(st.session_state.input_text)
    st.caption(f"{n:,} / {config.MAX_CHARS:,} characters")

    b1, b2 = st.columns([3, 1])
    with b1:
        translate = st.button("Translate", type="primary", use_container_width=True)
    b2.button("Clear", key="clear_input", on_click=clear_input, use_container_width=True)

    if translate:
        with st.spinner("Translating…"):
            run_translation()

    if msg := st.session_state.pop("flash", None):
        st.warning(msg)
    if err := st.session_state.pop("error", None):
        st.error(err, icon="⚠️")

    if st.session_state.result is not None:
        render_result(st.session_state.result)

    st.divider()
    render_history()


main()
