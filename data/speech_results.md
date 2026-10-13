### Whisper base on FLEURS (200 test clips, 40 per language)

| Language | WER | CER | Language identified |
|---|---|---|---|
| English | 9.3% | 4.2% | 100% |
| Spanish | 9.2% | 2.6% | 100% |
| French | 25.2% | 10.4% | 100% |
| German | 15.3% | 4.6% | 98% |
| Hindi | 106.0% | 90.2% | 85% |

Speed on the CPU used: 764 s to transcribe 2353 s of audio (real-time factor 0.32).

Speech translation into English, chrF / BLEU against the FLEURS English sentence. The three systems are compared on the same clips (those with every output recorded):

| Language | Clips compared | Cascade: Whisper + Google Translate | Whisper direct | Text only (no speech errors) | Whisper direct, all 40 clips |
|---|---|---|---|---|---|
| Spanish | 40 | 56.7 / 26.6 | 45.5 / 13.6 | 61.2 / 34.1 | 45.5 / 13.6 |
| French | 10 | 53.4 / 22.7 | 42.2 / 10.5 | 66.2 / 35.6 | 45.5 / 14.5 |
| German | 0 | – | – | – | 46.4 / 16.1 |
| Hindi | 0 | – | – | – | 28.7 / 3.5 |
