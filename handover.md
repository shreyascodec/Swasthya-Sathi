# Swasthya Sathi — Model Selection & Rationale

## Purpose

Swasthya Sathi is an offline, on-device system that turns a printed lab report into a verifiable structured record and runs a short spoken patient interview in the patient's own language. It uses several AI models, one per task, all running on a single low-power edge device (target: NVIDIA Jetson Orin NX, 16 GB).

This note explains which model we picked for each task and why, with two things kept in view: the licence (whether we can ship it commercially) and the technical fit (accuracy, speed, memory on limited hardware).

One point that matters for the filing: no model is hard-coded. Each one sits behind an interchangeable adapter and is chosen in a config file, so swapping a model is a config edit, not a code change. The invention is the overall architecture, the safety mechanisms, and the orchestration, not any single model. All the models are off-the-shelf. That is deliberate, and it keeps the claims broad.

## Summary

| Task | Model chosen | Licence | Why |
|---|---|---|---|
| OCR (text extraction) | RapidOCR (PP-OCR, ONNX) | Apache-2.0 | Clean licence, light runtime, F1 = 1.0 on printed English reports |
| Image typing | MobileNetV3-Small (fine-tuned) | Permissive (torchvision) | Right-sized classifier, roughly 65x faster and 18x lighter than a vision LLM |
| Summary (structuring) | Phi-3.5-mini via Ollama | MIT | Clean-licence replacement for Qwen; safe with the faithfulness gate |
| Speech-to-text | Whisper large-v3 + Vaani Hindi fine-tune | MIT engine (see caveat) | 100% recall of clinical entities on Hindi intake clips |
| Text-to-speech (Indic) | Kokoro-82M (Hindi) | Apache-2.0, voices included | Clean licence, CPU-friendly, fast, passed listen tests |
| Text-to-speech (English) | Piper (en_US-lessac-medium) | MIT engine, permissive voice | ARM-native, real-time, no GPU |

Every primary choice is on a permissive licence and can be shipped commercially. The one open licensing item is noted at the end.

## OCR — RapidOCR

We picked RapidOCR, the Apache-2.0 ONNX build of the PP-OCR family. The licence is clean and it runs on the ONNX runtime, which avoids the much heavier PaddlePaddle runtime that PaddleOCR needs. Accuracy is strong: field F1 = 1.0 in our benchmarks. We run it English-only on purpose, since roughly 99% of Indian lab reports are printed in English and turning on Devanagari only added misreads on English text.

We looked at PaddleOCR (same models, Apache-2.0, but heavier runtime) and Surya, and kept both as bench candidates. Cloud OCR (Google Document AI, AWS Textract, Azure Form Recognizer) was ruled out early: it needs internet, sends patient data off-device, and costs per page, none of which fits an offline, private design.

One thing worth flagging: OCR accuracy on real (not synthetic) Indian reports is not yet measured. That is validation work still to do, and it bears on any clinical claim.

## Image typing — MobileNetV3-Small

Sorting an image into one of four types (skin, eye, wound, oral) is a classification job, not work for a 4-billion-parameter language model. MobileNetV3 does it in about 0.05 s versus roughly 13 s, and in about 200 MB versus 3.7 GB. That alone removed image typing as the slowest stage. It also has an explicit "unknown" reject class, so junk or non-clinical input is set aside rather than forced into a category.

We kept MedGemma-4B zero-shot as the fallback: no training needed and it generalises better, but it is far slower. The current MobileNetV3 head is trained on a synthetic dataset we built, so it is working plumbing, not a clinically validated tagger. It only reports image type and quality, never a diagnosis.

## Summary / structuring — Phi-3.5-mini

This one is mainly a licensing decision. Phi-3.5-mini is MIT-licensed and fully clean to redistribute. We chose it to replace Qwen2.5-3B, which actually scored a little higher on faithfulness in our benchmarks but ships under the Qwen licence, not a standard permissive one. We took a small accuracy trade-off to get a clean licence.

For reference, Phi-3.5 came in around 0.89 to 0.92 on faithfulness at 6.5 to 7.3 s, while Qwen2.5-3B was around 0.97 to 0.98 at 6.1 to 6.6 s. Phi is a conditional yes: usable commercially as long as the deterministic faithfulness gate stays in place. That gate rejects any generated content not supported by the source text, so the model cannot invent a value, and the OCR output is kept as the floor so no measured value can be dropped. The safety guarantee is structural, not dependent on the model being perfect. Qwen, Sarvam-1-2B, MedGemma-4B, and Airavata-7B were kept only as bench candidates.

## Speech-to-text — Whisper large-v3 with a Hindi fine-tune

We run Whisper large-v3 through faster-whisper, with a Hindi fine-tune ("Vaani") as the Hindi engine, stock large-v3 as the non-Hindi fallback, and a small model as a cheap language checker. The Hindi fine-tune scored 12/12 on recall of the clinically important entities in our test clips, against 9/12 for stock large-v3 and 8/12 for IndicWhisper.

There is a safety wrinkle worth noting, since it is one of the novel features. The Hindi fine-tune is Hindi-output-only: given English audio it quietly transliterates into Devanagari and still reports full confidence, so it fails silently. To catch that, the kiosk's language selector picks the engine and a separate small model checks the language actually spoken, flagging a mismatch for review. Engine choice never rests on the model's own confidence.

The licence of the Vaani fine-tune weights still needs confirming (see below); the faster-whisper engine and base Whisper large-v3 are MIT.

## Text-to-speech — Kokoro (Indic) and Piper (English)

For Hindi we use Kokoro-82M. This was also a licence-driven switch. Every off-the-shelf Piper Hindi voice we found is non-commercial (CC-BY-NC-SA / IIT-M), even though Piper's engine is MIT. Kokoro gives us a Hindi voice that is Apache-2.0 including the voices, is CPU-friendly, fast, and passed listen tests. Because the spoken content is a fixed, clinician-signed set of questions, we precompute the phonemes at build time and assemble them at run time, so no heavy phonemiser runs on the device and speech stays fast and fully offline.

For English we use Piper with the en_US-lessac-medium voice: MIT engine, permissive voice, ARM-native, real-time, no GPU.

## Licensing items to confirm before shipping

1. The Hindi STT fine-tune ("Vaani" whisper-large-v3 weights): confirm the commercial redistribution terms of the fine-tuned weights specifically. The base Whisper and the faster-whisper runtime are MIT.
2. The Piper English voice (en_US-lessac-medium): confirm the specific voice model's terms for commercial redistribution.
3. Separate from models: the code was in a public GitHub repository. Under India's absolute-novelty standard (no grace period), a public disclosure with a running date may affect patentability. This was flagged in the disclosure form and should be reviewed independently.

All the primary choices (RapidOCR, MobileNetV3, Phi-3.5, Kokoro) are on permissive licences, and in several cases were chosen specifically to avoid non-commercial or non-standard licences on otherwise stronger alternatives (Qwen, the non-commercial Hindi Piper voices).

## Bottom line

Every model is off-the-shelf, picked for a clean commercial licence first and technical fit second, and swappable by config. What is patentable is the architecture and the safety mechanisms around these models, not the models themselves, which keeps the novelty independent of any third-party component or its licence.
