"""Download a small, fixed sample of FLEURS test recordings (google/fleurs, CC-BY 4.0).

    python -m eval.fleurs_sample          # ~200 clips into ~/.cache/translation_tool/fleurs

FLEURS reads the same English sentences (FLoRes) in 100+ languages, so a Spanish clip has an
English reference with the same sentence id. Only the first 40 clips of each language's test
archive are read: the archive is streamed and reading stops there, so a few MB are fetched
rather than the full split. The chosen clips are listed in data/fleurs_manifest.csv (committed);
the audio itself is not committed.
"""
from __future__ import annotations

import csv
import io
import os
import tarfile
from pathlib import Path

REPO = "google/fleurs"
REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"   # pinned
LANGS = {"en_us": "en", "es_419": "es", "fr_fr": "fr", "de_de": "de", "hi_in": "hi"}
PER_LANG = 40
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "fleurs_manifest.csv"
AUDIO_DIR = Path(os.environ.get("FLEURS_DIR", Path.home() / ".cache" / "translation_tool" / "fleurs"))


def _tsv(fs, lang: str, split: str) -> dict[str, dict]:
    path = f"datasets/{REPO}@{REVISION}/data/{lang}/{split}.tsv"
    rows = {}
    with fs.open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                rows[parts[1]] = {"sentence_id": parts[0], "file": parts[1], "raw": parts[2], "norm": parts[3]}
    return rows


def english_references(fs) -> dict[str, str]:
    """English text for every FLEURS sentence id (all splits), the translation reference."""
    refs = {}
    for split in ("test", "dev", "train"):
        for r in _tsv(fs, "en_us", split).values():
            refs.setdefault(r["sentence_id"], r["raw"])
    return refs


def main() -> int:
    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()
    english = english_references(fs)
    rows = []
    for lang, code in LANGS.items():
        meta = _tsv(fs, lang, "test")
        out = AUDIO_DIR / lang
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        with fs.open(f"datasets/{REPO}@{REVISION}/data/{lang}/audio/test.tar.gz", "rb", block_size=1 << 20) as fh:
            with tarfile.open(fileobj=fh, mode="r|gz") as tar:
                for member in tar:
                    name = Path(member.name).name
                    if not member.isfile() or name not in meta:
                        continue
                    (out / name).write_bytes(tar.extractfile(member).read())
                    m = meta[name]
                    rows.append({"lang": code, "fleurs_lang": lang, "file": name, "sentence_id": m["sentence_id"],
                                 "transcript": m["raw"], "english": english.get(m["sentence_id"], "")})
                    n += 1
                    if n == PER_LANG:
                        break
        print(f"{lang}: {n} clips", flush=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} clips -> {AUDIO_DIR}; manifest {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
