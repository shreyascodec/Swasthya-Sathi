# Commercial stack verdict — RapidOCR + Phi

Generated: 2026-08-05T09:19:53.584909+00:00

## OCR (RapidOCR / ONNX, Apache-2.0)
- Mean latency: **1.8317 s**/page (synthetic printed EN)
- Mean field F1: **1.0** (P=1.0, R=1.0)

## LLM summary
- `phi3.5:3.8b`: faith **0.8918**, F1 **0.6667**, latency **7.2956 s**, parse_errors=0
- `qwen2.5:3b-instruct`: faith **0.9722**, F1 **0.6**, latency **6.5753 s**, parse_errors=1

## Browser / API pipeline (SPA path)
- OCR engine seen: `rapidocr`, fields=10, faithfulness=0.875, total=17.1807 s

## Verdict
RapidOCR is **GO** for commercial English lab OCR on edge (F1>=0.85, latency OK). Phi-3.5 is **CONDITIONAL GO** for commercial distribution (MIT) — mean faithfulness slightly below Qwen; keep the deterministic gate and retune prompts/schema. Warm latency is competitive. Baseline Qwen2.5-3B: faith=0.9722, F1=0.6, lat=6.5753s (license: Qwen — not Apache).
