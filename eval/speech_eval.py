"""Evaluate speech recognition and speech translation on 200 FLEURS clips.

    python -m eval.fleurs_sample              # once: download the clips (~150 MB, not committed)
    python -m eval.speech_eval --record       # run Whisper and Google Translate, record outputs
    python -m eval.speech_eval                # recompute every number from the recorded outputs

Measured, per language (English, Spanish, French, German, Hindi; 40 clips each):
- word error rate (WER) and character error rate (CER) of Whisper base, after the usual
  normalisation (lower-case, punctuation removed);
- spoken-language identification accuracy;
- speech translation into English for the four non-English languages, scored with chrF and
  BLEU against FLEURS's English sentence for the same id. Three systems:
    cascade         Whisper transcript -> Google Translate (what the app does)
    whisper-direct  Whisper's built-in translate-to-English task
    text-only       the reference transcript -> Google Translate (an upper bound: no ASR errors)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "fleurs_manifest.csv"
OUTPUTS = ROOT / "data" / "speech_outputs.json"
RESULTS = ROOT / "data" / "speech_results.json"
RESULTS_MD = ROOT / "data" / "speech_results.md"
LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "hi": "Hindi"}


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = "".join(" " if unicodedata.category(c).startswith("P") else c for c in t)
    return re.sub(r"\s+", " ", t).strip()


def load_manifest() -> list[dict]:
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _patient(translate, text: str, source: str, waits=(20, 60)) -> str:
    """Free translation endpoints rate-limit bursts: pace requests and wait it out on errors."""
    import time

    from translation_tool.service import TranslationError

    for wait in (*waits, None):
        try:
            time.sleep(1.0)
            return translate(text, source=source, target="en").text
        except TranslationError:
            if wait is None:
                raise
            print(f"  rate limited; waiting {wait} s", file=sys.stderr, flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def record(rows: list[dict], outputs: dict) -> None:
    from eval.fleurs_sample import AUDIO_DIR
    from translation_tool.asr import Transcriber
    from translation_tool.service import TranslationService

    asr = Transcriber()
    mt = TranslationService()
    mt_blocked = False   # once the free services refuse us, stop asking this run; rerun later to fill in
    for i, r in enumerate(rows):
        key = f"{r['fleurs_lang']}/{r['file']}"
        o = outputs.setdefault(key, {})
        audio = AUDIO_DIR / r["fleurs_lang"] / r["file"]
        if "asr" not in o:
            t = asr.transcribe(audio)
            o["asr"] = {"text": t.text, "language": t.language, "p": round(t.language_probability, 4),
                        "duration": round(t.duration, 2), "seconds": round(t.seconds, 3)}
        if r["lang"] != "en":
            if "whisper_translate" not in o:
                o["whisper_translate"] = asr.transcribe(audio, task="translate").text
            for field, text in (("cascade", o["asr"]["text"]), ("text_only", r["transcript"])):
                if field in o or mt_blocked:
                    continue
                try:
                    o[field] = _patient(mt.translate, text, r["lang"])
                except Exception as exc:
                    print(f"  translation services unavailable ({exc}); recording speech only", file=sys.stderr)
                    mt_blocked = True
        if i % 20 == 19:
            OUTPUTS.write_text(json.dumps(outputs, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            print(f"  {i + 1}/{len(rows)}", file=sys.stderr, flush=True)


def compute(rows: list[dict], outputs: dict) -> dict:
    import jiwer
    import sacrebleu

    by_lang = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append((r, outputs[f"{r['fleurs_lang']}/{r['file']}"]))
    report = {"n": len(rows), "asr": {}, "translation": {}, "speed": {}}
    total_audio = total_secs = 0.0
    for lang, items in by_lang.items():
        refs = [normalise(r["transcript"]) for r, _ in items]
        hyps = [normalise(o["asr"]["text"]) for _, o in items]
        report["asr"][lang] = {
            "clips": len(items),
            "wer": jiwer.wer(refs, hyps), "cer": jiwer.cer(refs, hyps),
            "language_id": sum(o["asr"]["language"] == lang for _, o in items) / len(items),
        }
        total_audio += sum(o["asr"]["duration"] for _, o in items)
        total_secs += sum(o["asr"]["seconds"] for _, o in items)
        if lang == "en":
            continue
        english = [r["english"] for r, _ in items]
        both = [(r, o) for r, o in items if "cascade" in o and "text_only" in o]   # paired comparison set
        t = {"clips": len(items), "paired_clips": len(both),
             "whisper-direct (all clips)": {
                 "chrf": sacrebleu.corpus_chrf([o["whisper_translate"] for _, o in items], [english]).score,
                 "bleu": sacrebleu.corpus_bleu([o["whisper_translate"] for _, o in items], [english]).score}}
        if both:
            ref = [r["english"] for r, _ in both]
            for system, key in (("cascade", "cascade"), ("whisper-direct", "whisper_translate"), ("text-only", "text_only")):
                hyp = [o[key] for _, o in both]
                t[system] = {"chrf": sacrebleu.corpus_chrf(hyp, [ref]).score, "bleu": sacrebleu.corpus_bleu(hyp, [ref]).score}
        report["translation"][lang] = t
    report["speed"] = {"audio_seconds": round(total_audio, 1), "processing_seconds": round(total_secs, 1),
                       "real_time_factor": total_secs / total_audio}
    return report


def render(rep: dict) -> str:
    out = [f"### Whisper base on FLEURS ({rep['n']} test clips, 40 per language)", "",
           "| Language | WER | CER | Language identified |", "|---|---|---|---|"]
    for lang, a in rep["asr"].items():
        out.append(f"| {LANG_NAMES[lang]} | {100 * a['wer']:.1f}% | {100 * a['cer']:.1f}% | {100 * a['language_id']:.0f}% |")
    s = rep["speed"]
    out += ["", f"Speed on the CPU used: {s['processing_seconds']:.0f} s to transcribe {s['audio_seconds']:.0f} s of audio "
                f"(real-time factor {s['real_time_factor']:.2f}).", "",
            "Speech translation into English, chrF / BLEU against the FLEURS English sentence. The three "
            "systems are compared on the same clips (those with every output recorded):", "",
            "| Language | Clips compared | Cascade: Whisper + Google Translate | Whisper direct | Text only (no speech errors) | Whisper direct, all 40 clips |",
            "|---|---|---|---|---|---|"]
    for lang, t in rep["translation"].items():
        direct_all = t["whisper-direct (all clips)"]
        if t["paired_clips"]:
            cells = [f"{t[k]['chrf']:.1f} / {t[k]['bleu']:.1f}" for k in ("cascade", "whisper-direct", "text-only")]
        else:
            cells = ["–", "–", "–"]
        out.append(f"| {LANG_NAMES[lang]} | {t['paired_clips']} | " + " | ".join(cells)
                   + f" | {direct_all['chrf']:.1f} / {direct_all['bleu']:.1f} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", action="store_true", help="run Whisper / Google Translate for missing outputs")
    args = ap.parse_args(argv)
    rows = load_manifest()
    outputs = json.loads(OUTPUTS.read_text(encoding="utf-8")) if OUTPUTS.exists() else {}
    if args.record:
        try:
            record(rows, outputs)
        finally:
            OUTPUTS.write_text(json.dumps(outputs, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    report = compute(rows, outputs)
    RESULTS.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    md = render(report)
    RESULTS_MD.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
