# Hindi-path deciding verdict — RapidOCR + Phi

Generated: 2026-08-05T09:28:40.187927+00:00

## Scope
Hindi patient path: EN lab OCR -> faithful EN summary (clinician) -> HI closed-bank spoken intake.

## OCR (shared; reports are English)
- Mean latency: **7.9474 s**/page
- Mean field F1: **1.0**

## Hindi closed-bank intake
- Sessions with all questions in-bank: **100%**
- Sessions with all Devanagari: **100%**
- Mean questions/session: **5.0**

## LLM with patient_language=hi
- `phi3.5:3.8b`: faith **0.9214**, F1 **0.76**, latency **6.5827 s**, parse_errors=0
- `qwen2.5:3b-instruct`: faith **0.9833**, F1 **1.0**, latency **6.106 s**, parse_errors=0

## Browser / API (lang=hi)
- OCR=`rapidocr`, fields=10, faith=0.875, questions=5, all_Devanagari=True, total=40.1963s
  - [hi] आपका हीमोग्लोबिन 9.5 g/dL है, जो कम है। क्या आप अक्सर थकान, कमजोरी या सांस फूलने का अनुभव करते हैं?
  - [hi] आज आप किस मुख्य स्वास्थ्य समस्या के लिए आए हैं?
  - [hi] क्या आप इस समय कोई दवा ले रहे हैं? यदि हाँ, तो कौन सी?
  - [hi] आपके वर्तमान लक्षण कब से हैं?
  - [hi] क्या आपको दवा या भोजन से कोई ज्ञात एलर्जी है?

## Verdict
OCR on Hindi-path sessions: **GO** (English report digitisation holds). Hindi closed-bank intake: **GO** (100% Devanagari + in-bank). Phi on lang=hi: **CONDITIONAL GO** — usable with faithfulness gate; below Qwen on raw faith, but MIT-distributable. Qwen baseline lang=hi: faith=0.9833, F1=1.0, lat=6.106s. Browser Hindi path: **PASS** — 5 Devanagari questions, OCR=rapidocr, faith=0.875, total=40.1963s. **DECIDING FACTOR: APPROVE RapidOCR + Phi for Hindi-path commercial trial** with mandatory faithfulness gate and prompt polish before production.
