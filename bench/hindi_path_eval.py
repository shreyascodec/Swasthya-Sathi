"""Hindi-path deciding bake-off: RapidOCR + Phi with lang=hi.

Priority surface for Swasthya Sathi is the Hindi patient path:
  English printed report OCR -> faithful EN clinical summary -> Hindi intake
  questions from the closed bank (text_hi + slot fill) -> (optional) Hindi TTS.

Usage:
    .\\.venv\\Scripts\\python.exe -m bench.hindi_path_eval
    .\\.venv\\Scripts\\python.exe -m bench.hindi_path_eval --browser
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import models  # noqa: F401
from bench.commercial_stack_eval import (
    SYNTH_DIR,
    browser_pipeline,
    eval_llm,
    eval_ocr,
    render_lab_page,
)
from bench.dataset import load_eval_set
from core.env import AppConfig
from stages.intake_qa_rules import (
    IntakeFacts,
    LabFact,
    load_question_bank,
    select,
    validate_from_bank,
)

RESULTS = Path(__file__).resolve().parent / "results"
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _has_deva(s: str) -> bool:
    return bool(_DEVANAGARI.search(s or ""))


def eval_hindi_intake(items, max_items: int = 5) -> dict:
    """Closed-bank Hindi question selection — the patient-facing Hindi surface."""
    bank = load_question_bank()
    cfg = AppConfig.load("dev_4060").stages.get("intake_qa", {})
    max_q = int(cfg.get("max_questions", 5))
    stale = int(cfg.get("stale_report_months", 6))

    per = []
    for item in items[:max_items]:
        gold = item.gold or {}
        labs = []
        present = set()
        # Prefer interpreted-style status from gold values when possible: treat
        # presence of findings as lab facts with unknown status so triggers that
        # need high/low may not fire — also feed OCR fields as LabFact unknown.
        for f in gold.get("lab_findings", []):
            labs.append(LabFact(
                analyte=str(f.get("analyte", "")),
                value=str(f.get("value", "")),
                unit=f.get("unit"),
                status="unknown",
            ))
            present.add(str(f.get("analyte", "")).strip().lower())
        # Enrich status from interpretations if gold has them
        for fl in gold.get("interpretations", []) or []:
            labs.append(LabFact(
                analyte=str(fl.get("analyte", "")),
                value=str(fl.get("value", "")),
                unit=fl.get("unit"),
                status=str(fl.get("status", "unknown")),
            ))
            present.add(str(fl.get("analyte", "")).strip().lower())

        # Also use OCR field names for missing_test presence set
        for f in item.ocr_fields:
            if f.name and f.name.lower() not in {"facility", "doctor", "date"} and not f.name.endswith("ref-range"):
                present.add(f.name.strip().lower())

        facts = IntakeFacts(
            labs=labs,
            present_analytes=present,
            report_dates=list(gold.get("report_dates") or []),
            medications=[m.get("name", "") for m in gold.get("medications", []) if m.get("name")],
        )
        chosen = select(bank, facts, max_questions=max_q, stale_report_months=stale)
        rows = []
        all_in_bank = True
        all_hi = True
        for q in chosen:
            ok_bank = validate_from_bank(q.pattern_id, bank)
            hi = q.text_hi
            slots_ok = "{" not in hi  # slots should be filled
            has_hi = _has_deva(hi)
            all_in_bank = all_in_bank and ok_bank
            all_hi = all_hi and has_hi
            rows.append({
                "pattern_id": q.pattern_id,
                "category": q.category,
                "in_bank": ok_bank,
                "has_devanagari": has_hi,
                "slots_filled": slots_ok,
                "text_hi": hi,
                "text_en": q.text_en,
            })
        per.append({
            "id": item.id,
            "n_questions": len(chosen),
            "all_in_bank": all_in_bank,
            "all_devanagari": all_hi,
            "questions": rows,
        })

    n = len(per) or 1
    return {
        "n": len(per),
        "pct_all_in_bank": round(sum(1 for p in per if p["all_in_bank"]) / n, 4),
        "pct_all_devanagari": round(sum(1 for p in per if p["all_devanagari"]) / n, 4),
        "mean_questions": round(sum(p["n_questions"] for p in per) / n, 2),
        "per_item": per,
    }


def _questions_from_ctx(ctx: dict) -> list[dict]:
    qs = (ctx or {}).get("questions") or []
    out = []
    for q in qs:
        text = q.get("rendered_text") or q.get("text") or ""
        out.append({
            "id": q.get("id") or q.get("pattern_id"),
            "pattern_id": q.get("pattern_id"),
            "lang": q.get("lang"),
            "text": text,
            "has_devanagari": _has_deva(text),
        })
    return out


def browser_hindi(base: str, png: Path) -> dict:
    """Drive browser API with lang=hi through voice pause (Hindi Q&A gate)."""
    import httpx

    t_all = time.perf_counter()
    with httpx.Client(base_url=base, timeout=300.0) as client:
        for _ in range(60):
            body = client.get("/api/ready").json()
            if body.get("ready") or not body.get("warming"):
                break
            time.sleep(1)
        ready = client.get("/api/ready").json()
        sess = client.post("/api/session", json={"lang": "hi"}).json()
        sid = sess["session_id"]
        with png.open("rb") as f:
            client.post(
                f"/api/session/{sid}/upload",
                files={"files": (png.name, f, "image/png")},
            ).raise_for_status()

        stage_times = []
        questions_hi = []
        for _ in range(16):
            snap = client.get(f"/api/session/{sid}").json()
            paused = snap.get("paused") or {}
            if paused.get("kind") == "flag":
                client.post(f"/api/session/{sid}/resume", json={"action": "continue"})
                continue
            if paused.get("kind") == "intake_qa":
                questions_hi = _questions_from_ctx(snap.get("ctx") or {})
                break
            if paused.get("kind") == "error":
                stage_times.append({"error_pause": paused})
                break

            t0 = time.perf_counter()
            r = client.post(f"/api/session/{sid}/run-stage")
            elapsed = time.perf_counter() - t0
            if r.status_code >= 400:
                stage_times.append({"error": r.text, "latency_s": round(elapsed, 4)})
                break
            body = r.json()
            stages = body.get("stages") or []
            last = next(
                (s for s in reversed(stages) if s.get("status") in ("done", "flagged", "error")),
                None,
            )
            stage_times.append({
                "stage": last["name"] if last else None,
                "status": last["status"] if last else None,
                "elapsed_ui": last.get("elapsed") if last else None,
                "latency_s": round(elapsed, 4),
            })
            paused = body.get("paused") or {}
            if paused.get("kind") == "intake_qa":
                questions_hi = _questions_from_ctx(body.get("ctx") or {})
                break
            if body.get("done"):
                break

        final = client.get(f"/api/session/{sid}").json()
        if not questions_hi:
            questions_hi = _questions_from_ctx(final.get("ctx") or {})
        faith = (final.get("derived") or {}).get("faithfulness") or {}
        ocr = (final.get("ctx") or {}).get("ocr") or {}
        audio = (final.get("ctx") or {}).get("audio_out") or []
        return {
            "session_id": sid,
            "lang": final.get("lang") or "hi",
            "ready": ready,
            "total_s": round(time.perf_counter() - t_all, 4),
            "ocr_engine": ocr.get("engine"),
            "n_ocr_fields": len(ocr.get("fields") or []),
            "faithfulness": faith.get("score"),
            "faithfulness_ok": faith.get("ok"),
            "faith_issues": faith.get("issues") or [],
            "n_questions": len(questions_hi),
            "questions_all_devanagari": all(q.get("has_devanagari") for q in questions_hi) if questions_hi else False,
            "questions": questions_hi,
            "n_audio_clips": len(audio),
            "stages": stage_times,
            "paused": final.get("paused"),
        }


def decide_hindi_verdict(payload: dict) -> str:
    ocr = payload.get("ocr") or {}
    phi = next((m for m in payload.get("llms") or [] if "phi" in str(m.get("model", "")).lower()), None)
    qwen = next((m for m in payload.get("llms") or [] if "qwen2.5:3b" in str(m.get("model", "")).lower()), None)
    intake = payload.get("hindi_intake") or {}
    br = payload.get("browser") or {}

    bits = []
    # OCR still English reports even on Hindi path
    if (ocr.get("mean_f1") or 0) >= 0.85:
        bits.append("OCR on Hindi-path sessions: **GO** (English report digitisation holds).")
    else:
        bits.append("OCR on Hindi-path sessions: **NO-GO**.")

    # Closed-bank Hindi is the product invariant
    if (intake.get("pct_all_devanagari") or 0) >= 0.99 and (intake.get("pct_all_in_bank") or 0) >= 0.99:
        bits.append("Hindi closed-bank intake: **GO** (100% Devanagari + in-bank).")
    elif (intake.get("pct_all_devanagari") or 0) >= 0.9:
        bits.append("Hindi closed-bank intake: **CONDITIONAL GO**.")
    else:
        bits.append("Hindi closed-bank intake: **NO-GO** — patient Hindi surface broken.")

    if phi and not phi.get("unavailable"):
        faith = phi.get("mean_faithfulness") or 0
        if faith >= 0.95:
            bits.append("Phi on lang=hi summaries: **GO**.")
        elif faith >= 0.85:
            bits.append(
                "Phi on lang=hi: **CONDITIONAL GO** — usable with faithfulness gate; "
                "below Qwen on raw faith, but MIT-distributable."
            )
        else:
            bits.append("Phi on lang=hi: **NO-GO** for Hindi-path primary.")
    if qwen and not qwen.get("unavailable"):
        bits.append(
            f"Qwen baseline lang=hi: faith={qwen.get('mean_faithfulness')}, "
            f"F1={qwen.get('mean_f1')}, lat={qwen.get('mean_latency_s')}s."
        )

    if br and not br.get("error"):
        if br.get("questions_all_devanagari") and (br.get("n_questions") or 0) > 0:
            bits.append(
                f"Browser Hindi path: **PASS** — {br.get('n_questions')} Devanagari questions, "
                f"OCR={br.get('ocr_engine')}, faith={br.get('faithfulness')}, total={br.get('total_s')}s."
            )
        elif (br.get("n_questions") or 0) == 0:
            bits.append("Browser Hindi path: **FAIL** — no intake questions surfaced.")
        else:
            bits.append("Browser Hindi path: **FAIL** — questions missing Devanagari.")

    # Deciding factor rollup
    intake_ok = (intake.get("pct_all_devanagari") or 0) >= 0.99
    phi_ok = phi and not phi.get("unavailable") and (phi.get("mean_faithfulness") or 0) >= 0.85
    browser_ok = bool(br.get("questions_all_devanagari")) and (br.get("n_questions") or 0) > 0
    if intake_ok and phi_ok and (browser_ok or not br):
        bits.append(
            "**DECIDING FACTOR: APPROVE RapidOCR + Phi for Hindi-path commercial trial** "
            "with mandatory faithfulness gate and prompt polish before production."
        )
    elif intake_ok and not phi_ok:
        bits.append(
            "**DECIDING FACTOR: HOLD Phi** — Hindi bank is fine; keep Qwen (or Apache Qwen2.5-1.5B/7B) until Phi faith improves."
        )
    else:
        bits.append("**DECIDING FACTOR: BLOCK** — Hindi patient surface or OCR/LLM bar not met.")
    return " ".join(bits)


def verdict_md(payload: dict) -> str:
    ocr = payload.get("ocr") or {}
    intake = payload.get("hindi_intake") or {}
    llms = payload.get("llms") or []
    br = payload.get("browser") or {}
    lines = [
        "# Hindi-path deciding verdict — RapidOCR + Phi",
        "",
        f"Generated: {payload.get('ts')}",
        "",
        "## Scope",
        "Hindi patient path: EN lab OCR -> faithful EN summary (clinician) -> HI closed-bank spoken intake.",
        "",
        "## OCR (shared; reports are English)",
        f"- Mean latency: **{ocr.get('mean_latency_s')} s**/page",
        f"- Mean field F1: **{ocr.get('mean_f1')}**",
        "",
        "## Hindi closed-bank intake",
        f"- Sessions with all questions in-bank: **{(intake.get('pct_all_in_bank') or 0)*100:.0f}%**",
        f"- Sessions with all Devanagari: **{(intake.get('pct_all_devanagari') or 0)*100:.0f}%**",
        f"- Mean questions/session: **{intake.get('mean_questions')}**",
        "",
        "## LLM with patient_language=hi",
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
    lines += ["", "## Browser / API (lang=hi)"]
    if br.get("error"):
        lines.append(f"- Failed: {br['error']}")
    else:
        lines.append(
            f"- OCR=`{br.get('ocr_engine')}`, fields={br.get('n_ocr_fields')}, "
            f"faith={br.get('faithfulness')}, questions={br.get('n_questions')}, "
            f"all_Devanagari={br.get('questions_all_devanagari')}, total={br.get('total_s')}s"
        )
        for q in br.get("questions") or []:
            lines.append(f"  - [{q.get('lang')}] {q.get('text')}")
    lines += ["", "## Verdict", payload.get("verdict", "")]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int, default=5)
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--models", default="phi3.5:3.8b,qwen2.5:3b-instruct")
    args = ap.parse_args()

    items = [i for i in load_eval_set() if i.lang == "hi"]
    print(f"Hindi eval items: {len(items)} (using {args.max_items})")

    print("=== OCR (hi-session reports) ===")
    ocr = eval_ocr(items, args.max_items)
    print(json.dumps({k: ocr[k] for k in ocr if k != "per_item"}, indent=2))

    print("=== Hindi closed-bank intake ===")
    # Enrich facts with interpret statuses via pipeline-like LabQAR when possible
    from stages.interpret_rules import load_reference_table, interpret_value
    table = load_reference_table("data/labqar/reference_ranges_labqar.yaml")
    for item in items[: args.max_items]:
        interps = []
        for f in item.gold.get("lab_findings", []):
            try:
                result = interpret_value(
                    str(f.get("analyte", "")),
                    str(f.get("value", "")),
                    f.get("unit"),
                    printed_ref=f.get("ref_range"),
                    table=table,
                )
                status = getattr(result, "status", None) or "unknown"
            except Exception:
                status = "unknown"
            interps.append({
                "analyte": f.get("analyte"),
                "value": f.get("value"),
                "unit": f.get("unit"),
                "status": status,
            })
        item.gold["interpretations"] = interps
    intake = eval_hindi_intake(items, args.max_items)
    print(json.dumps({k: intake[k] for k in intake if k != "per_item"}, indent=2))

    llms = []
    for mid in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"=== LLM {mid} (patient_language=hi) ===")
        block = eval_llm(mid, items, args.max_items)
        print(json.dumps({k: block[k] for k in block if k != "per_item"}, indent=2))
        llms.append(block)

    browser = {}
    if args.browser:
        item = items[0]
        png = SYNTH_DIR / f"{item.id}_hi_browser.png"
        render_lab_page(item, png)
        print(f"=== Browser Hindi path @ {args.base} ===")
        try:
            browser = browser_hindi(args.base, png)
            print(json.dumps({k: browser[k] for k in browser if k != "questions"}, indent=2))
            print("questions:", json.dumps(browser.get("questions"), ensure_ascii=False, indent=2))
        except Exception as exc:
            browser = {"error": str(exc)}
            print("Browser failed:", exc)

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": "hindi",
        "ocr": ocr,
        "hindi_intake": intake,
        "llms": llms,
        "browser": browser,
    }
    payload["verdict"] = decide_hindi_verdict(payload)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "hindi_path_verdict.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md = verdict_md(payload)
    (RESULTS / "hindi_path_verdict.md").write_text(md, encoding="utf-8")
    # ASCII-safe console print
    sys.stdout.buffer.write(md.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
