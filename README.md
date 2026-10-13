# 🌐 Language Translation Tool

[![tests](https://github.com/Shivani-Radhakrishnan/CodeAlpha_LanguageTranslationTool/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Shivani-Radhakrishnan/CodeAlpha_LanguageTranslationTool/actions/workflows/tests.yml)

A Streamlit app that translates text between 100+ languages. It can detect the source language, read the translation aloud in the browser, and save it as a file. Behind the UI is a small, typed service layer. It tries each translation service in turn, retries failed requests, puts a time limit on each one, caches results, and shows a clear message when the network is down. A pytest suite covers it with all network calls mocked. Built for the CodeAlpha internship.

It also does **speech-to-speech**: record yourself in any of about 100 languages and hear the translation. Whisper (running locally, no PyTorch) works out which language you spoke, the text is translated, and the result is read aloud. On 200 recordings from the FLEURS benchmark, Whisper base gets **9.2% word error rate in Spanish and 9.3% in English**, and recognising speech then translating it beats Whisper's own built-in translation by **11 chrF points** on Spanish.

![Screenshot of the app translating Spanish to English](assets/screenshot.png)

*Screenshot of the app running locally with `streamlit run app.py`. The result shows "via MyMemory" because Google rate-limited that machine, so the app fell back to the second service on its own.*

## Features

- **Auto-detect** the source language, shown with a confidence score ("Detected Spanish (100%)").
- **Swap languages (⇄)**: the translation moves into the input box. This also works after auto-detect, using the detected language.
- **Character counter** with a 5,000-character limit and input validation.
- **Listen 🔊**: [gTTS](https://pypi.org/project/gTTS/) creates an MP3 that plays in the browser.
- **Download .txt** and **Copy text** for the translation.
- **History** of the last 10 translations in the session, with *Use again* and *Clear*.
- **Line breaks kept**, so paragraphs stay paragraphs.
- **Fallback between services**: if Google Translate fails or rate-limits, the app tries MyMemory automatically.
- **Clear error states**: a network outage shows *"Couldn't reach the translation service… check your internet connection"*, not a stack trace.

## Speech-to-speech

The **🎙️ Speak** tab records from the microphone (or takes an audio file), then:

```
speech ──► Whisper base (faster-whisper / CTranslate2, int8 on CPU; ~145 MB)
              detects the spoken language and transcribes it
       ──► TranslationService (the same Google → MyMemory chain as typed text)
       ──► gTTS ──► the translation, played in the browser
```

It shows what it heard and how sure it is of the language ("Heard (Spanish, 100% sure)"), so a
misheard word is visible before you rely on the translation.

### Measured on FLEURS

[FLEURS](https://huggingface.co/datasets/google/fleurs) (CC BY 4.0) has native speakers reading
the same English source sentences in 100+ languages, so a Spanish recording has an English
reference translation. I took the first 40 test recordings in each of five languages
(`data/fleurs_manifest.csv`; `python -m eval.fleurs_sample` downloads them, 200 clips).

| Language | Word error rate | Character error rate | Language identified correctly |
|---|---|---|---|
| English | 9.3% | 4.2% | 100% |
| Spanish | 9.2% | 2.6% | 100% |
| French | 25.2% | 10.4% | 100% |
| German | 15.3% | 4.6% | 98% |
| Hindi | 106.0% | 90.2% | 85% |

Speech translation into English (chrF / BLEU against the FLEURS English sentence), comparing
the app's design (recognise, then translate) with Whisper's built-in translate-to-English task
and with translating the correct transcript (the ceiling if speech recognition were perfect):

| Language | Clips | Whisper + Google Translate (the app) | Whisper's own translation | Perfect transcript + Google |
|---|---|---|---|---|
| Spanish | 40 | **56.7** / 26.6 | 45.5 / 13.6 | 61.2 / 34.1 |
| French | 10 | **53.4** / 22.7 | 42.2 / 10.5 | 66.2 / 35.6 |

- **Recognise-then-translate beats Whisper's own translation** by about 11 chrF points, and
  speech-recognition errors cost about 4.5 points against a perfect transcript (Spanish).
- **Hindi is where the base model breaks down.** It usually recognises that the speaker is using
  Hindi (85% of clips) but writes the words in Urdu or Latin script instead
  of Devanagari, so almost every word counts as an error against the reference
  (106% word error rate). The sounds are often right ("Television Reporter may plant se
  nikalne wala..."). The larger Whisper models, or forcing Devanagari output, are the fix; I have
  not measured either here.
- **French and German translation comparisons are incomplete**: Google Translate's free endpoint
  and MyMemory rate-limited this machine during the run, so only the clips listed were
  translated. Whisper's own translation was scored on all 40 clips per language
  (chrF 45.5 French, 46.4 German, 28.7 Hindi). The comparison will be filled in by rerunning
  `python -m eval.speech_eval --record`, which resumes where it stopped.
- Speed: 764 s to transcribe 2353 s of audio on an M1 Mac CPU
  (about 3x faster than real time, while another training job shared the CPU).

Every Whisper and translation output is recorded in `data/speech_outputs.json`, so
`python -m eval.speech_eval` recomputes every number above without the audio or the model (the
tests check this).

## How it works

```
app.py (Streamlit UI, session state only)
   │
   ▼
TranslationService.translate(text, source, target)
   ├─ validate: non-empty, ≤ 5,000 chars, known language codes
   ├─ LRU cache (256 entries) → repeated requests make no network call
   ├─ detect source offline with langdetect (when "Auto-detect")
   └─ for each provider (Google → MyMemory):
         split into lines, then into chunks no longer than the provider's limit
         each request: 10 s timeout, 1 retry with backoff for errors that may clear up (rate limit, network, timeout)
         unsupported language pair → skip to the next provider
```

| Module | Responsibility |
|---|---|
| `translation_tool/providers.py` | `TranslationProvider` interface. `GoogleProvider` and `MyMemoryProvider` (both via [deep-translator](https://pypi.org/project/deep-translator/)) turn library and HTTP errors into `ProviderError(transient=…)`. |
| `translation_tool/service.py` | Validation, retries, timeouts, choosing the next service, chunking, caching. Raises `InputError` or `TranslationError` with messages that are safe to show users. |
| `translation_tool/languages.py` | Language table (offline) and deterministic `langdetect` detection, with its codes mapped to Google's (`he` → `iw`, `zh-cn` → `zh-CN`). |
| `translation_tool/speech.py` | gTTS text-to-speech as MP3 bytes, with timeout and error handling. |
| `translation_tool/asr.py` | Whisper speech recognition (faster-whisper), language detection, and the Whisper ↔ Google language-code mapping (`he` ↔ `iw`, `zh` ↔ `zh-CN`). |
| `translation_tool/voice.py` | Speech-to-speech: transcribe, translate from the detected language, synthesise. |
| `eval/` | FLEURS sample download (`fleurs_sample.py`) and the speech evaluation (`speech_eval.py`). |
| `translation_tool/config.py` | All limits, timeouts and defaults in one place. |

**Libraries used.** The original version used `googletrans==4.0.0-rc1`, an unmaintained release candidate that breaks whenever Google changes its web page. `deep-translator` is maintained, and it sits behind the provider interface, so it can be swapped out without touching the UI. deep-translator has no request timeout of its own, so the service runs each call in a worker thread with a deadline.

**Why gTTS, not pyttsx3.** pyttsx3 speaks through the *server's* speakers. A user on a deployed app hears nothing, and on headless Linux (CI, Streamlit Cloud, Docker) it fails because there is no audio device. gTTS returns an MP3, and `st.audio` plays it in the user's browser.

## Quick start

```bash
git clone https://github.com/Shivani-Radhakrishnan/CodeAlpha_LanguageTranslationTool.git
cd CodeAlpha_LanguageTranslationTool
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-speech.txt   # optional: the Speak tab (faster-whisper)
streamlit run app.py
```

Use the service from Python:

```python
from translation_tool.service import TranslationService

result = TranslationService().translate("¿Dónde está la biblioteca?", "auto", "en")
print(result.text, result.detected_source, result.provider)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite makes **no real API calls**: `tests/conftest.py` blocks socket connections for every test. It covers:

- input validation and the character limit
- retries with backoff, timeouts, and falling back to the next service
- the friendly offline message
- caching (hits, separate entries per language pair, LRU eviction, failures not cached)
- keeping line breaks, and chunking long text
- provider error handling, including the real deep-translator parser fed a mocked HTTP response
- MyMemory language-code mapping and its error-as-text responses
- language detection
- text-to-speech
- UI tests with `streamlit.testing.AppTest`: translate, swap, listen, history, HTML escaping, error banners
- speech recognition with a fake Whisper model (segments joined, language codes mapped, silence and
  unreadable audio give friendly errors), the speech-to-speech pipeline, and that the published
  FLEURS numbers recompute from the recorded outputs

CI runs the suite on Python 3.10 and 3.12.

## Limitations

- **Depends on free web services.** Google Translate's free web endpoint and MyMemory are unofficial or free tiers without an SLA. They can rate-limit (Google answers HTTP 429 to heavy or shared IPs) or change without notice. For production use, add a provider for a paid API (Google Cloud Translation, DeepL) by implementing `TranslationProvider`.
- MyMemory accepts at most 500 characters per request (the app splits text into chunks) and has a daily free quota.
- Auto-detect is statistical. Very short text (one or two words) may be detected wrongly or not at all; in that case the app leaves detection to Google, and MyMemory is skipped.
- Text-to-speech covers 65 of the 133 languages and reads at most the first 1,000 characters.
- History lives in the browser session and is lost on refresh.
- Speech recognition uses Whisper *base* for speed and size; it is weak on some languages (see the
  Hindi result above). The model size is one setting in `translation_tool/asr.py`.

## License

[MIT](LICENSE)
