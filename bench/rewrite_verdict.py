"""Rewrite commercial_stack_verdict.md from the JSON artifact (ASCII-safe)."""
from __future__ import annotations
import json
from pathlib import Path

p = Path(__file__).resolve().parent / "results" / "commercial_stack_verdict.json"
payload = json.loads(p.read_text(encoding="utf-8"))
ocr = payload.get("ocr") or {}
llms = payload.get("llms") or []
br = payload.get("browser") or {}

# refresh verdict without unicode
from bench.commercial_stack_eval import decide_verdict, verdict_text
payload["verdict"] = decide_verdict(payload)
md = verdict_text(payload)
out = Path(__file__).resolve().parent / "results" / "commercial_stack_verdict.md"
out.write_text(md, encoding="utf-8")
p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(md)
