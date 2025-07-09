import streamlit as st
from googletrans import Translator, LANGUAGES
import pyttsx3
import time

st.set_page_config(
    page_title="🌍 Language Translator",
    page_icon="🌐",
    layout="centered",
)

translator = Translator()
engine = pyttsx3.init()

if 'history' not in st.session_state:
    st.session_state.history = []

st.markdown(
    """
    <style>
    body {
        background-color: #f0f2f6;
    }
    .main {
        background: linear-gradient(to bottom right, #f9fcff, #e0eafc);
        border-radius: 15px;
        padding: 2rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        animation: fadeIn 1.2s ease-in;
    }
    @keyframes fadeIn {
        from {opacity: 0; transform: translateY(20px);}
        to {opacity: 1; transform: translateY(0);}
    }
    .stTextInput, .stTextArea, .stSelectbox, .stButton {
        animation: fadeIn 0.8s ease-in-out;
        text-indent: 12px;
    }
    .translation {
        font-size: 1.2rem;
        padding: 1rem;
        background-color: #0f0d0d;
        border-radius: 12px;
        box-shadow: inset 0 0 6px rgba(0,0,0,0.05);
        animation: slideUp 0.8s ease-in-out;
    }
    @keyframes slideUp {
        from {opacity: 0; transform: translateY(30px);}
        to {opacity: 1; transform: translateY(0);}
    }
    </style>
    """,
    unsafe_allow_html=True
)

with st.container():
    st.markdown("<h1 style='text-align: center;'>🌍 Language Translation Tool</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size:18px; color:#555;'>Smart Translator with Auto-Detect & History</p>", unsafe_allow_html=True)

text = st.text_area("📝 Enter text to translate", "")

lang_list = ["Auto Detect"] + list(LANGUAGES.values())
lang_code_map = {v: k for k, v in LANGUAGES.items()}

source_lang = st.selectbox("🌐 Source Language", lang_list, index=0)
target_lang = st.selectbox("🎯 Target Language", lang_list[1:], index=lang_list.index("hindi") - 1)

col1, col2 = st.columns([1, 3])
with col1:
    translate_btn = st.button("🔁 Translate")
with col2:
    speak_btn = st.button("🔊 Speak Output")

if translate_btn and text:
    src_code = 'auto' if source_lang == "Auto Detect" else lang_code_map[source_lang]
    tgt_code = lang_code_map[target_lang]
    with st.spinner("Translating..."):
        time.sleep(1)
        translated = translator.translate(text, src=src_code, dest=tgt_code)
        st.markdown(f"<div class='translation'>📌 <b>Translation:</b><br>{translated.text}</div>", unsafe_allow_html=True)

        st.session_state.history.append({
            "Input": text,
            "From": translated.src if src_code == "auto" else source_lang,
            "To": target_lang,
            "Output": translated.text
        })

if speak_btn and st.session_state.get("history"):
    last = st.session_state.history[-1]["Output"]
    engine.say(last)
    engine.runAndWait()

if st.session_state.history:
    st.markdown("### 🕘 Translation History")
    for i, item in enumerate(reversed(st.session_state.history[-5:]), 1):
        with st.expander(f"{i}. {item['From']} ➡ {item['To']}"):
            st.write(f"**Input:** {item['Input']}")
            st.write(f"**Output:** {item['Output']}")

st.markdown("<hr style='margin-top:3rem'>", unsafe_allow_html=True)