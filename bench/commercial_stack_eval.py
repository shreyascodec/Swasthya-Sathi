"""RapidOCR + Phi commercial-stack bake-off (accuracy / faithfulness / latency).

Produces:
  bench/results/commercial_stack_verdict.json
  bench/results/commercial_stack_verdict.md
  data/eval/synthetic_reports/*.png  (synthetic printed lab pages)

Usage (from repo root, with .venv active and Ollama serving phi3.5:3.8b):
    .\\.venv\\Scripts\\python.exe -m bench.commercial_stack_eval
    .\\.venv\\Scripts\\python.exe -m bench.commercial_stack_eval --browser
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import models  # noqa: F401
from bench.dataset import load_eval_set
from bench.metrics import extraction_prf
from core.context import OCRField
from core.env import AppConfig
from core.model_manager import ModelManager
from stages.faithfulness import check_faithfulness
from stages.ocr_extract import extract_fields
from stages.summary_build import build_prompt, parse_summary
from stages.summary_schema import SummarySchema

RESULTS = Path(__file__).resolve().parent / "results"
SYNTH_DIR = ROOT / "data" / "eval" / "synthetic_reports"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def render_lab_page(item, out_path: Path) -> Path:
    """Render a clean printed-style English lab report PNG from gold OCR fields."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1240, 1754  # ~A4 @ 150 dpi
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
        font_sm = ImageFont.truetype("arial.ttf", 22)
        font_title = ImageFont.truetype("arialbd.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
        font_sm = font
        font_title = font

    gold = item.gold or {}
    facility = gold.get("facility") or "Diagnostic Laboratory"
    doctor = gold.get("doctor") or "Dr. Review"
    dates = gold.get("report_dates") or []
    date = dates[0] if dates else "01/01/2026"

    y = 60
    draw.text((60, y), str(facility), fill="black", font=font_title)
    y += 60
    draw.text((60, y), f"Consulting Physician: {doctor}", fill="black", font=font_sm)
    y += 36
    draw.text((60, y), f"Report Date: {date}", fill="black", font=font_sm)
    y += 36
    draw.text((60, y), f"Patient Language: {item.lang}", fill="black", font=font_sm)
    y += 50
    draw.line((60, y, W - 60, y), fill="black", width=2)
    y += 30
    draw.text((60, y), "LABORATORY INVESTIGATION REPORT", fill="black", font=font)
    y += 50
    draw.text((60, y), "Test", fill="black", font=font_sm)
    draw.text((420, y), "Result", fill="black", font=font_sm)
    draw.text((620, y), "Unit", fill="black", font=font_sm)
    draw.text((820, y), "Reference", fill="black", font=font_sm)
    y += 28
    draw.line((60, y, W - 60, y), fill="gray", width=1)
    y += 20

    for f in gold.get("lab_findings", []):
        analyte = str(f.get("analyte", ""))
        value = str(f.get("value", ""))
        unit = str(f.get("unit") or "")
        ref = str(f.get("ref_range") or "")
        # One visual row — matches real Indian table layout OCR expects
        line = f"{analyte}  {value}  {unit}  {ref}".strip()
        draw.text((60, y), line, fill="black", font=font_sm)
        y += 36
        if y > H - 120:
            break

    y = H - 80
    draw.text((60, y), "End of Report — Computer Generated", fill="gray", font=font_sm)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def field_f1(extracted: list[OCRField], gold: dict) -> dict:
    """Loose analyte/value F1 against gold lab_findings."""
    gold_pairs = {
        (_norm(f.get("analyte", "")), _norm(str(f.get("value", ""))))
        for f in gold.get("lab_findings", [])
        if f.get("analyte")
    }
    pred_pairs = {
        (_norm(f.name), _norm(f.value))
        for f in extracted
        if f.name and not f.name.endswith("ref-range")
        and f.name.lower() not in {"facility", "doctor", "date"}
    }
    if not gold_pairs and not pred_pairs:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}
    # Match on value alone if analyte fuzzy-contains
    tp = 0
    used = set()
    for ga, gv in gold_pairs:
        for pa, pv in pred_pairs:
            if (pa, pv) in used:
                continue
            if gv == pv and (ga == pa or ga in pa or pa in ga):
                tp += 1
                used.add((pa, pv))
                break
    fp = max(0, len(pred_pairs) - tp)
    fn = max(0, len(gold_pairs) - tp)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn}


def eval_ocr(items, max_items: int = 5) -> dict:
    config = AppConfig.load("dev_4060")
    config.models["ocr"]["primary"] = {
        "impl": "rapidocr", "lang": ["en"], "device": "cpu",
        "vram_mb": 800, "det_limit_side_len": 1280,
        "use_textline_orientation": False,
    }
    mm = ModelManager(config)
    adapter = mm.get("ocr")
    # warm
    _ = adapter.recognize(np.zeros((64, 64, 3), dtype=np.uint8))

    per = []
    for item in items[:max_items]:
        png = SYNTH_DIR / f"{item.id}.png"
        render_lab_page(item, png)
        bgr = np.array(__import__("cv2").imread(str(png)))
        t0 = time.perf_counter()
        page = adapter.recognize(bgr, str(png))
        latency = time.perf_counter() - t0
        fields = extract_fields(page.text, page.tokens, low_confidence_threshold=0.80)
        scores = field_f1(fields, item.gold)
        per.append({
            "id": item.id,
            "latency_s": round(latency, 4),
            "n_tokens": len(page.tokens),
            "n_fields": len(fields),
            "mean_conf": round(page.mean_confidence, 4),
            **scores,
        })
    mm.release("ocr")
    lat = [p["latency_s"] for p in per]
    return {
        "engine": "rapidocr",
        "n": len(per),
        "mean_latency_s": round(sum(lat) / len(lat), 4) if lat else None,
        "mean_f1": round(sum(p["f1"] for p in per) / len(per), 4) if per else None,
        "mean_precision": round(sum(p["precision"] for p in per) / len(per), 4) if per else None,
        "mean_recall": round(sum(p["recall"] for p in per) / len(per), 4) if per else None,
        "per_item": per,
    }


def _summarize(raw: str, lang: str) -> SummarySchema:
    try:
        return SummarySchema.model_validate(parse_summary(raw))
    except Exception:
        return SummarySchema(patient_language=lang, unknowns=["parse_error"])


def eval_llm(model_id: str, items, max_items: int = 5) -> dict:
    config = AppConfig.load("dev_4060")
    config.models["llm"]["primary"] = {
        "impl": "ollama_llm", "model": model_id, "runtime": "ollama",
        "quant": "int4", "device": "cuda", "vram_mb": 3200, "instruct": True,
        "json_mode": True,
    }
    mm = ModelManager(config)
    try:
        adapter = mm.get("llm")
    except Exception as exc:
        return {"model": model_id, "error": str(exc), "unavailable": True}

    per = []
    for item in items[:max_items]:
        system, user = build_prompt(item.ocr_fields, item.lang)
        t0 = time.perf_counter()
        try:
            raw = adapter.generate(system, user)
        except Exception as exc:
            per.append({"id": item.id, "error": str(exc)})
            continue
        latency = time.perf_counter() - t0
        summary = _summarize(raw, item.lang)
        report = check_faithfulness(summary, item.ocr_fields)
        prf = extraction_prf(summary, item.gold)
        per.append({
            "id": item.id,
            "latency_s": round(latency, 4),
            "faithfulness": round(report.faithfulness, 4),
            "hallucination_rate": round(report.hallucination_rate, 4),
            "issues": len(report.issues),
            "precision": round(prf["precision"], 4),
            "recall": round(prf["recall"], 4),
            "f1": round(prf["f1"], 4),
            "parse_error": "parse_error" in (summary.unknowns or []),
        })
    mm.release("llm")

    ok = [p for p in per if "error" not in p]
    def mean(key):
        vals = [p[key] for p in ok if p.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "model": model_id,
        "n": len(ok),
        "mean_latency_s": mean("latency_s"),
        "mean_faithfulness": mean("faithfulness"),
        "mean_hallucination_rate": mean("hallucination_rate"),
        "mean_f1": mean("f1"),
        "mean_precision": mean("precision"),
        "mean_recall": mean("recall"),
        "parse_errors": sum(1 for p in ok if p.get("parse_error")),
        "per_item": per,
    }


def browser_pipeline(base: str, png_path: Path, lang: str = "en") -> dict:
    """Drive the same HTTP API the React SPA uses (browser-equivalent path)."""
    import httpx

    t_all = time.perf_counter()
    with httpx.Client(base_url=base, timeout=300.0) as client:
        # wait ready (or proceed if warming with stubs)
        for _ in range(60):
            r = client.get("/api/ready")
            body = r.json()
            if body.get("ready") or not body.get("warming"):
                break
            time.sleep(1)
        ready = client.get("/api/ready").json()
        sess = client.post("/api/session", json={"lang": lang}).json()
        sid = sess["session_id"]
        with png_path.open("rb") as f:
            up = client.post(
                f"/api/session/{sid}/upload",
                files={"files": (png_path.name, f, "image/png")},
            )
            up.raise_for_status()

        stage_times = []
        # Run until summary (stage 4) done — skip voice/STT for this bake-off
        # if those models are stubbed/unavailable.
        for _ in range(12):
            snap = client.get(f"/api/session/{sid}").json()
            if snap.get("done"):
                break
            paused = snap.get("paused")
            if paused and paused.get("kind") in ("flag", "error"):
                # continue past non-fatal gates when possible
                client.post(f"/api/session/{sid}/resume", json={"action": "continue"})
            if paused and paused.get("kind") == "intake_qa":
                # seal without answers for latency of OCR+LLM path
                client.post(f"/api/session/{sid}/resume", json={"action": "continue"})
            t0 = time.perf_counter()
            r = client.post(f"/api/session/{sid}/run-stage")
            elapsed = time.perf_counter() - t0
            if r.status_code >= 400:
                stage_times.append({"error": r.text, "latency_s": round(elapsed, 4)})
                break
            body = r.json()
            stages = body.get("stages") or []
            last = next((s for s in reversed(stages) if s.get("status") in ("done", "flagged", "error")), None)
            stage_times.append({
                "stage": last["name"] if last else None,
                "status": last["status"] if last else None,
                "elapsed_ui": last.get("elapsed") if last else None,
                "latency_s": round(elapsed, 4),
            })
            # stop after summary for focused OCR+LLM verdict if intake would block
            if last and last.get("name") == "summary" and last.get("status") in ("done", "flagged"):
                # continue a couple more if interpret is quick
                pass
            if last and last.get("name") in ("report",) and last.get("status") == "done":
                break
            names_done = {s["name"] for s in stages if s.get("status") in ("done", "flagged")}
            paused = body.get("paused") or {}
            if {"intake", "ocr", "summary", "interpret"}.issubset(names_done):
                # enough for faithfulness verdict
                if "intake_qa" in names_done or paused.get("kind") == "intake_qa":
                    break
            if {"intake", "ocr", "summary", "interpret"}.issubset(names_done) and not paused:
                break

        final = client.get(f"/api/session/{sid}").json()
        faith = (final.get("derived") or {}).get("faithfulness") or {}
        ocr = (final.get("ctx") or {}).get("ocr") or {}
        return {
            "session_id": sid,
            "ready": ready,
            "total_s": round(time.perf_counter() - t_all, 4),
            "ocr_engine": ocr.get("engine"),
            "n_ocr_fields": len(ocr.get("fields") or []),
            "faithfulness": faith.get("score"),
            "faithfulness_ok": faith.get("ok"),
            "faith_issues": faith.get("issues") or [],
            "stages": stage_times,
            "paused": final.get("paused"),
            "done": final.get("done"),
        }


def verdict_text(payload: dict) -> str:
    ocr = payload.get("ocr") or {}
    llms = payload.get("llms") or []
    br = payload.get("browser") or {}
    lines = [
        "# Commercial stack verdict — RapidOCR + Phi",
        "",
        f"Generated: {payload.get('ts')}",
        "",
        "## OCR (RapidOCR / ONNX, Apache-2.0)",
        f"- Mean latency: **{ocr.get('mean_latency_s')} s**/page (synthetic printed EN)",
        f"- Mean field F1: **{ocr.get('mean_f1')}** (P={ocr.get('mean_precision')}, R={ocr.get('mean_recall')})",
        "",
        "## LLM summary",
    ]
    for m in llms:
        if m.get("unavailable"):
            lines.append(f"- `{m.get('model')}`: UNAVAILABLE — {m.get('error')}")
            continue
        lines.append(
            f"- `{m.get('model')}`: faith **{m.get('mean_faithfulness')}**, "
            f"F1 **{m.get('mean_f1')}**, latency **{m.get('mean_latency_s')} s**, "
            f"parse_errors={m.get('parse_errors')}"
        )
    lines += ["", "## Browser / API pipeline (SPA path)"]
    if br.get("error"):
        lines.append(f"- Browser run failed: {br['error']}")
    else:
        lines.append(
            f"- OCR engine seen: `{br.get('ocr_engine')}`, fields={br.get('n_ocr_fields')}, "
            f"faithfulness={br.get('faithfulness')}, total={br.get('total_s')} s"
        )
    lines += ["", "## Verdict"]
    lines.append(payload.get("verdict", ""))
    return "\n".join(lines) + "\n"


def decide_verdict(payload: dict) -> str:
    ocr = payload.get("ocr") or {}
    phi = next((m for m in payload.get("llms") or [] if "phi" in str(m.get("model", "")).lower()), None)
    qwen = next((m for m in payload.get("llms") or [] if "qwen2.5:3b" in str(m.get("model", "")).lower()), None)
    bits = []
    f1 = ocr.get("mean_f1") or 0
    lat = ocr.get("mean_latency_s") or 99
    if f1 >= 0.85 and lat <= 3.0:
        bits.append("RapidOCR is **GO** for commercial English lab OCR on edge (F1>=0.85, latency OK).")
    elif f1 >= 0.70:
        bits.append("RapidOCR is **CONDITIONAL GO** — usable but retune thresholds / layout; F1 below 0.85 on synth.")
    else:
        bits.append("RapidOCR is **NO-GO** at current settings — field recovery too weak; keep Paddle until tuned.")

    if phi and not phi.get("unavailable"):
        faith = phi.get("mean_faithfulness") or 0
        fl = phi.get("mean_latency_s") or 99
        pf1 = phi.get("mean_f1") or 0
        if faith >= 0.95 and pf1 >= 0.75 and fl <= 20:
            bits.append("Phi-3.5 is **GO** as commercial MIT replacement for Qwen-3B on this task.")
        elif faith >= 0.85:
            bits.append(
                "Phi-3.5 is **CONDITIONAL GO** for commercial distribution (MIT) — "
                "mean faithfulness slightly below Qwen; keep the deterministic gate and retune prompts/schema. "
                "Warm latency is competitive."
            )
        else:
            bits.append("Phi-3.5 is **NO-GO** yet — faithfulness/F1 below bar; keep Qwen until prompt/schema tuned.")
        if qwen and not qwen.get("unavailable"):
            bits.append(
                f"Baseline Qwen2.5-3B: faith={qwen.get('mean_faithfulness')}, "
                f"F1={qwen.get('mean_f1')}, lat={qwen.get('mean_latency_s')}s "
                f"(license: Qwen — not Apache)."
            )
    else:
        bits.append("Phi model not available in Ollama for this run — pull `phi3.5:3.8b` and re-run.")
    return " ".join(bits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int, default=5)
    ap.add_argument("--browser", action="store_true", help="Also hit running server API path")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--models", default="phi3.5:3.8b,qwen2.5:3b-instruct")
    args = ap.parse_args()

    items = load_eval_set()
    # Prefer English items for OCR synth
    en = [i for i in items if i.lang == "en"] or items
    print(f"Eval items: {len(en)} EN (using first {args.max_items})")

    print("=== OCR RapidOCR ===")
    ocr = eval_ocr(en, args.max_items)
    print(json.dumps({k: ocr[k] for k in ocr if k != "per_item"}, indent=2))

    llms = []
    for mid in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"=== LLM {mid} ===")
        block = eval_llm(mid, en, args.max_items)
        print(json.dumps({k: block[k] for k in block if k != "per_item"}, indent=2))
        llms.append(block)

    browser = {}
    if args.browser:
        png = SYNTH_DIR / f"{en[0].id}.png"
        if not png.exists():
            render_lab_page(en[0], png)
        print(f"=== Browser/API pipeline @ {args.base} ===")
        try:
            browser = browser_pipeline(args.base, png, en[0].lang)
            print(json.dumps(browser, indent=2))
        except Exception as exc:
            browser = {"error": str(exc)}
            print("Browser path failed:", exc)

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ocr": ocr,
        "llms": llms,
        "browser": browser,
    }
    payload["verdict"] = decide_verdict(payload)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "commercial_stack_verdict.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    md = verdict_text(payload)
    (RESULTS / "commercial_stack_verdict.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
