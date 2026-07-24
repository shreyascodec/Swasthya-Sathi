"""MedGemma-4B MULTIMODAL bake-off — text + report page images in ONE call.

This is the deep-dive the stakeholders asked for: instead of feeding MedGemma
only OCR *text*, we feed it the OCR text AND the rendered report page images
(multiple pages per patient) and ask for ONE consolidated summary whose
narrative fuses every page into a single paragraph.

To show what the image actually BUYS, we run two conditions on the SAME items:

  * text_only  — OCR text only (baseline; what the current pipeline does).
  * text+image — same OCR text but every low-confidence field is MASKED out of
                 the text ("[UNREADABLE — read from image]"), while the page
                 image still shows the true value. A field recovered here came
                 from vision, not from the text. That is the `vision_recovery`
                 metric.

Everything is a real measurement on the 4060 (INT4). New stakeholder parameters:
  - n_pages / latency per call and per page, p90, and the 90 s BUDGET verdict
  - vram_peak_mb (measured, not budgeted)
  - vision_recovery: fraction of masked (OCR-unreadable) fields the model read
    correctly from the image
  - cross-page coverage: fraction of all pages' gold findings present in output
  - faithfulness / hallucination (same safety gate) and extraction F1

Run (on the 4060, MedGemma cached / HF_TOKEN set):
    python -m bench.make_eval_multi        # once
    python -m bench.runner_mm              # text+image + text-only conditions
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.dataset import EvalItem, load_eval_set
from bench.metrics import extraction_prf, faithfulness, hindi_quality, percentile
from core.context import OCRField
from stages.faithfulness import check_faithfulness
from stages.summary_build import parse_summary
from stages.summary_schema import SummarySchema

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "bench" / "results_mm"
MULTI_EVAL = ROOT / "data" / "eval" / "eval_set_multi.json"
MODEL_ID = "google/medgemma-4b-it"
BUDGET_S = 90.0

MASK = "[UNREADABLE — read from image]"

SYSTEM_MM = (
    "You are a medical record structuring assistant for a point-of-care kiosk. "
    "You DO NOT diagnose. You consolidate one patient's MULTIPLE lab report "
    "pages into a single structured summary. RULES:\n"
    "1. Every value MUST come either from the provided OCR text OR be read "
    "directly from the attached report page images. Never invent a value.\n"
    "2. Some OCR fields are marked '" + MASK + "'. For those, READ the value "
    "from the matching report image. If you still cannot read it, put its name "
    "in 'unknowns'.\n"
    "3. Combine ALL pages. 'narrative_en' must be ONE single paragraph that "
    "fuses the findings from every page together (do not write one sentence "
    "per page in isolation).\n"
    "Return ONLY a JSON object matching the schema — no prose, no code fences."
)

SCHEMA_HINT = {
    "patient_language": "hi",
    "facility": "string or null",
    "report_dates": ["string"],
    "lab_findings": [
        {"analyte": "string", "value": "string", "unit": "string or null",
         "ref_range": "string or null", "source_field": "OCR field name"}
    ],
    "medications": [{"name": "string", "source_field": "OCR field name"}],
    "narrative_en": "one combined paragraph",
    "unknowns": ["string"],
}


def _mask_low_conf(fields: list[OCRField]) -> tuple[list[dict], list[OCRField]]:
    """Return (text_fields_for_prompt, masked_field_truth).

    text_fields_for_prompt has low-confidence values replaced by MASK.
    masked_field_truth are the OCRFields whose value we hid (their true value
    must be recovered from the image to score vision_recovery).
    """
    out: list[dict] = []
    masked: list[OCRField] = []
    for f in fields:
        if f.low_confidence:
            out.append({"name": f.name, "value": MASK, "unit": f.unit})
            masked.append(f)
        else:
            out.append({"name": f.name, "value": f.value, "unit": f.unit})
    return out, masked


def _all_fields_json(text_fields: list[dict]) -> str:
    return json.dumps(text_fields, ensure_ascii=False)


def _build_messages(item: EvalItem, use_images: bool, mask: bool):
    """Build the chat messages for the processor (text + optional images)."""
    from PIL import Image

    if mask:
        text_fields, masked = _mask_low_conf(item.ocr_fields)
    else:
        text_fields = [{"name": f.name, "value": f.value, "unit": f.unit}
                       for f in item.ocr_fields]
        masked = []

    user_text = (
        f"patient_language: {item.lang}\n"
        f"This patient has {item.n_pages} report page(s).\n\n"
        f"Schema to fill (types are hints):\n"
        f"{json.dumps(SCHEMA_HINT, ensure_ascii=False)}\n\n"
        f"OCR text extracted from the pages:\n{_all_fields_json(text_fields)}\n\n"
        f"Produce the consolidated JSON summary now."
    )

    content = []
    imgs = []
    if use_images:
        for p in item.page_images:
            img = Image.open(p).convert("RGB")
            imgs.append(img)
            content.append({"type": "image", "image": img})
    content.append({"type": "text", "text": user_text})

    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_MM}]},
        {"role": "user", "content": content},
    ]
    return messages, masked, imgs


class MedGemmaMM:
    """MedGemma-4B multimodal handle (INT4), loaded once, reused per item."""

    def __init__(self):
        import torch
        from transformers import (AutoProcessor, BitsAndBytesConfig,
                                   AutoModelForImageTextToText)

        self.torch = torch
        quant = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        self.processor = AutoProcessor.from_pretrained(MODEL_ID)
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID, quantization_config=quant, device_map="auto",
            dtype=torch.bfloat16,
        )
        self.model.eval()

    def generate(self, messages, max_new_tokens: int = 1024) -> str:
        torch = self.torch
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(self.model.device)
        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=self.processor.tokenizer.eos_token_id,
            )
        return self.processor.tokenizer.decode(
            out[0][input_len:], skip_special_tokens=True)


def _summarize(raw: str, lang: str) -> SummarySchema:
    try:
        return SummarySchema.model_validate(parse_summary(raw))
    except Exception:
        return SummarySchema(patient_language=lang, unknowns=["parse_error"])


def _vision_recovery(summary: SummarySchema, masked: list[OCRField]) -> float | None:
    """Fraction of masked fields whose TRUE value appears in the summary output."""
    if not masked:
        return None
    text = " ".join(
        [summary.narrative_en]
        + [f"{f.analyte} {f.value}" for f in summary.lab_findings]
    )
    hit = 0
    for f in masked:
        if f.value and f.value in text:
            hit += 1
    return round(hit / len(masked), 4)


def _coverage(summary: SummarySchema, gold: dict) -> float:
    """Fraction of gold lab findings (across ALL pages) present in output."""
    gold_pairs = {(g["analyte"].lower(), str(g["value"]).lower())
                  for g in gold.get("lab_findings", [])}
    pred_pairs = {(f.analyte.lower(), f.value.lower()) for f in summary.lab_findings}
    if not gold_pairs:
        return 1.0
    return round(len(gold_pairs & pred_pairs) / len(gold_pairs), 4)


def run_condition(handle: MedGemmaMM, items: list[EvalItem], *,
                  use_images: bool, mask: bool, label: str) -> dict:
    torch = handle.torch
    per_item: list[dict] = []
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    for item in items:
        messages, masked, imgs = _build_messages(item, use_images, mask)
        t0 = time.perf_counter()
        raw = handle.generate(messages)
        latency = time.perf_counter() - t0
        for im in imgs:
            im.close()

        summary = _summarize(raw, item.lang)
        report = check_faithfulness(summary, item.ocr_fields)
        prf = extraction_prf(summary, item.gold)
        hq = hindi_quality(summary, item.gold) if item.lang == "hi" else None
        vr = _vision_recovery(summary, masked) if (use_images and mask) else None

        per_item.append({
            "id": item.id, "lang": item.lang, "n_pages": item.n_pages,
            "latency_s": round(latency, 4),
            "latency_per_page_s": round(latency / max(item.n_pages, 1), 4),
            "faithfulness": round(report.faithfulness, 4),
            "hallucination_rate": round(report.hallucination_rate, 4),
            "f1": round(prf["f1"], 4),
            "coverage": _coverage(summary, item.gold),
            "hindi_quality": hq,
            "vision_recovery": vr,
            "under_budget": latency <= BUDGET_S,
        })
        print(f"    [{label}] {item.id} pages={item.n_pages} "
              f"lat={latency:5.1f}s faith={report.faithfulness:.2f} "
              f"f1={prf['f1']:.2f} cover={per_item[-1]['coverage']:.2f} "
              f"vrec={vr}", file=sys.stderr)

    vram_peak = (int(torch.cuda.max_memory_allocated() // (1024 * 1024))
                 if torch.cuda.is_available() else 0)

    def mean(key, cond=lambda pi: True):
        vals = [pi[key] for pi in per_item if cond(pi) and pi[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    lats = [pi["latency_s"] for pi in per_item]
    return {
        "label": label,
        "use_images": use_images,
        "masked_low_conf": mask,
        "vram_peak_mb": vram_peak,
        "metrics": {
            "faithfulness": mean("faithfulness"),
            "hallucination_rate": mean("hallucination_rate"),
            "extraction_f1": mean("f1"),
            "coverage": mean("coverage"),
            "hindi_quality": mean("hindi_quality", lambda pi: pi["lang"] == "hi"),
            "vision_recovery": mean("vision_recovery",
                                    lambda pi: pi["vision_recovery"] is not None),
            "latency_s_mean": round(sum(lats) / len(lats), 4) if lats else 0.0,
            "latency_s_p90": round(percentile(lats, 0.9), 4),
            "latency_s_max": round(max(lats), 4) if lats else 0.0,
            "latency_per_page_mean": mean("latency_per_page_s"),
            "budget_pass_rate": round(
                sum(1 for pi in per_item if pi["under_budget"]) / len(per_item), 4)
            if per_item else 0.0,
        },
        "per_item": per_item,
    }


def run(out_dir: Path, conditions: list[str]) -> dict:
    items = load_eval_set(MULTI_EVAL)
    print(f"Loaded {len(items)} multi-report items "
          f"({sum(i.n_pages for i in items)} pages).", file=sys.stderr)

    print("Loading MedGemma-4B (INT4, multimodal)...", file=sys.stderr)
    handle = MedGemmaMM()

    results = []
    if "text_only" in conditions:
        results.append(run_condition(handle, items, use_images=False,
                                     mask=False, label="text_only"))
    if "text_image" in conditions:
        results.append(run_condition(handle, items, use_images=True,
                                     mask=True, label="text+image"))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL_ID,
        "budget_s": BUDGET_S,
        "dataset": {
            "n_items": len(items),
            "n_pages_total": sum(i.n_pages for i in items),
            "langs": {l: sum(1 for i in items if i.lang == l)
                      for l in {i.lang for i in items}},
        },
        "conditions": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest_mm.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(out, out_dir / "summary_mm.csv")
    _write_report(out, out_dir / "REPORT_MM.md")
    return out


_COLS = ["faithfulness", "hallucination_rate", "extraction_f1", "coverage",
         "hindi_quality", "vision_recovery", "latency_s_mean", "latency_s_p90",
         "latency_s_max", "latency_per_page_mean", "budget_pass_rate"]


def _write_csv(out: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["condition", "vram_peak_mb", *_COLS])
        for c in out["conditions"]:
            w.writerow([c["label"], c["vram_peak_mb"],
                        *[c["metrics"][k] for k in _COLS]])


def _write_report(out: dict, path: Path) -> None:
    d = out["dataset"]
    lines = [
        "# MedGemma-4B — Text + Image (Multimodal) Bake-off",
        "",
        f"- Generated: {out['generated_at']}  ·  Model: `{out['model']}`  ·  INT4 on RTX 4060",
        f"- Dataset: {d['n_items']} multi-page patients, {d['n_pages_total']} report "
        f"pages total {d['langs']}",
        f"- Budget: **{out['budget_s']:.0f} s per consolidated summary**",
        "",
        "## Results",
        "",
        "| Condition | Faithful | Halluc. | Extract F1 | Coverage | Hindi | "
        "Vision recovery | Lat mean | Lat p90 | Lat max | s/page | ≤90s | VRAM peak |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in out["conditions"]:
        m = c["metrics"]
        vr = f"{m['vision_recovery']:.2f}" if c["use_images"] and c["masked_low_conf"] else "—"
        lines.append(
            f"| {c['label']} | {m['faithfulness']:.2f} | {m['hallucination_rate']:.2f} | "
            f"{m['extraction_f1']:.2f} | {m['coverage']:.2f} | {m['hindi_quality']:.2f} | "
            f"{vr} | {m['latency_s_mean']:.1f}s | {m['latency_s_p90']:.1f}s | "
            f"{m['latency_s_max']:.1f}s | {m['latency_per_page_mean']:.1f}s | "
            f"{m['budget_pass_rate']*100:.0f}% | {c['vram_peak_mb']} MB |"
        )
    lines += [
        "",
        "## What the new parameters mean",
        "- **Coverage**: fraction of lab findings across ALL pages that made it into "
        "the one consolidated summary (multi-report consolidation quality).",
        "- **Vision recovery**: fields OCR marked low-confidence were BLANKED from the "
        "text; this is the fraction MedGemma read correctly straight from the page "
        "image. It isolates what image analysis adds on top of OCR.",
        "- **s/page** and **≤90s**: latency normalized per page and the fraction of "
        "consolidated summaries that finished inside the 90 s kiosk budget.",
        "- **VRAM peak**: measured peak allocation (INT4) — must fit the 8 GB 4060 "
        "alongside the other stages.",
        "",
        "## Method",
        "One MedGemma-4B call per patient consumes every page image plus the OCR text "
        "and returns a single consolidated summary whose narrative fuses all pages "
        "into one paragraph. `text_only` is the same call without images (baseline). "
        "Faithfulness is checked against the full OCR record with the product's gate.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="MedGemma multimodal bake-off.")
    p.add_argument("--out", default=str(RESULTS_DIR))
    p.add_argument("--conditions", default="text_only,text_image",
                   help="comma list: text_only,text_image")
    args = p.parse_args(argv)
    conds = [c.strip() for c in args.conditions.split(",")]
    out = run(Path(args.out), conds)
    print("\nMultimodal bake-off complete. Wrote latest_mm.json, summary_mm.csv, "
          "REPORT_MM.md")
    for c in out["conditions"]:
        m = c["metrics"]
        print(f"  {c['label']:<12} faith={m['faithfulness']:.2f} "
              f"f1={m['extraction_f1']:.2f} cover={m['coverage']:.2f} "
              f"vrec={m['vision_recovery']:.2f} lat_mean={m['latency_s_mean']:.1f}s "
              f"p90={m['latency_s_p90']:.1f}s budget<=90s={m['budget_pass_rate']*100:.0f}% "
              f"vram={c['vram_peak_mb']}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
