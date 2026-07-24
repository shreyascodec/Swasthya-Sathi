"""Model bake-off harness for Stage [4] Summary Generation.

Runs each candidate LLM (Qwen2.5-3B / Sarvam-1-2B / MedGemma-4B) over a labeled
Hindi+English eval set and scores faithfulness/hallucination, field-extraction
accuracy, Hindi quality, latency, and VRAM — then emits stakeholder proof
(results JSON + CSV + markdown report + charts, and a Canvas dashboard).

Run on the 4060:  python -m bench.runner
"""
