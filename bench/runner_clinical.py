"""MedGemma-4B clinical-image bench — TYPE + QUALITY (scored) and an ungrounded
ASSESSMENT probe (unscored).

Reuses the multimodal MedGemma handle from runner_mm. For each image MedGemma
returns one JSON object:
  * image_type        skin | eye | wound | oral | unknown      (SCORED vs label)
  * type_confidence   0..1
  * is_clinical_image bool                                     (guardrail on junk)
  * quality           usable | unusable                        (SCORED vs label)
  * quality_reason    short string
  * assessment        free text                                (UNSCORED probe)

SCORING HONESTY: images are synthetic placeholders (see make_clinical_set.py), so
we score only what synthetic images can legitimately support — TYPE classification,
QUALITY flag, and junk rejection. The `assessment` field exists because it was
explicitly requested; it is recorded RAW and never scored, because there is no
real pathology to be right or wrong about. It must not be shown to stakeholders as
evidence of diagnostic capability, and it conflicts with the product's
type+quality-only, never-diagnosis invariant (stages/s3_imagetag.py).

Run (4060, MedGemma cached):
    python -m bench.make_clinical_set
    python -m bench.runner_clinical
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.metrics import percentile
from bench.runner_mm import MedGemmaMM
from stages.summary_build import parse_summary

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "clinical" / "index.json"
RESULTS_DIR = ROOT / "bench" / "results_clinical"
CLASSES = ["skin", "eye", "wound", "oral", "unknown"]

SYSTEM = (
    "You are a clinical-image INTAKE assistant for a self-service health kiosk. "
    "For the single attached image, return a JSON object with these keys:\n"
    '  "image_type": one of ["skin","eye","wound","oral","unknown"] — the body '
    "region / image kind. Use \"unknown\" if it is not clearly one of these or "
    "not a clinical photo at all.\n"
    '  "type_confidence": number 0..1\n'
    '  "is_clinical_image": true only if this looks like a real clinical photo\n'
    '  "quality": "usable" or "unusable" (blurry, dark, or unreadable -> unusable)\n'
    '  "quality_reason": short string\n'
    '  "assessment": brief factual visual observation\n'
    "Return ONLY the JSON object, no prose, no code fences."
)

USER = "Classify this image and return the JSON object."


def _load_index() -> list[dict]:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    return data.get("items", [])


def _parse(raw: str) -> dict:
    try:
        return parse_summary(raw)
    except Exception:
        return {"image_type": "parse_error", "type_confidence": 0.0,
                "is_clinical_image": None, "quality": "parse_error",
                "quality_reason": "", "assessment": raw[:200]}


def _build_messages(img):
    return [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM}]},
        {"role": "user", "content": [
            {"type": "image", "image": img},
            {"type": "text", "text": USER},
        ]},
    ]


def run(out_dir: Path) -> dict:
    from PIL import Image

    items = _load_index()
    print(f"Loaded {len(items)} synthetic clinical images.", file=sys.stderr)
    print("Loading MedGemma-4B (INT4, multimodal)...", file=sys.stderr)
    handle = MedGemmaMM()
    torch = handle.torch
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    per_item: list[dict] = []
    for it in items:
        path = ROOT / "data" / "clinical" / it["path"]
        img = Image.open(path).convert("RGB")
        t0 = time.perf_counter()
        raw = handle.generate(_build_messages(img), max_new_tokens=384)
        latency = time.perf_counter() - t0
        img.close()

        pred = _parse(raw)
        ptype = str(pred.get("image_type", "unknown")).lower().strip()
        if ptype not in CLASSES:
            ptype = "unknown"
        pqual = str(pred.get("quality", "")).lower().strip()

        type_ok = (ptype == it["intended_type"])
        # For junk, "unknown" OR is_clinical_image=false both count as correct.
        if it["intended_type"] == "unknown":
            type_ok = (ptype == "unknown") or (pred.get("is_clinical_image") is False)
        qual_ok = (pqual == it["quality"]) if pqual in ("usable", "unusable") else False

        per_item.append({
            "path": it["path"],
            "intended_type": it["intended_type"],
            "pred_type": ptype,
            "type_confidence": pred.get("type_confidence"),
            "is_clinical_image": pred.get("is_clinical_image"),
            "intended_quality": it["quality"],
            "pred_quality": pqual,
            "type_correct": type_ok,
            "quality_correct": qual_ok,
            "latency_s": round(latency, 3),
            "assessment_raw": str(pred.get("assessment", ""))[:400],  # UNSCORED
        })
        print(f"    {it['path']:<22} intended={it['intended_type']:<7} "
              f"pred={ptype:<7} q={pqual:<8} type_ok={type_ok} "
              f"lat={latency:4.1f}s", file=sys.stderr)

    vram_peak = (int(torch.cuda.max_memory_allocated() // (1024 * 1024))
                 if torch.cuda.is_available() else 0)

    # --- scored aggregates (type + quality + junk rejection only) -----------
    clinical = [p for p in per_item if p["intended_type"] != "unknown"]
    junk = [p for p in per_item if p["intended_type"] == "unknown"]
    lats = [p["latency_s"] for p in per_item]

    def frac(rows, key):
        return round(sum(1 for r in rows if r[key]) / len(rows), 4) if rows else 0.0

    # per-class type accuracy
    per_class = {}
    for cls in ["skin", "eye", "wound", "oral"]:
        rows = [p for p in per_item if p["intended_type"] == cls]
        per_class[cls] = frac(rows, "type_correct")

    metrics = {
        "type_accuracy_overall": frac(clinical, "type_correct"),
        "type_accuracy_per_class": per_class,
        "quality_accuracy": frac(per_item, "quality_correct"),
        "junk_rejection_rate": frac(junk, "type_correct"),
        "latency_s_mean": round(sum(lats) / len(lats), 3) if lats else 0.0,
        "latency_s_p90": round(percentile(lats, 0.9), 3),
        "vram_peak_mb": vram_peak,
    }

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": "google/medgemma-4b-it",
        "SYNTHETIC": True,
        "warning": ("Synthetic placeholder images — NO real pathology. TYPE/QUALITY/"
                    "junk metrics test behavior & plumbing only. The 'assessment' "
                    "field is UNSCORED and ungrounded; do not treat it as diagnostic "
                    "capability. Diagnosis also breaks the product's no-diagnosis "
                    "invariant (stages/s3_imagetag.py)."),
        "n_images": len(per_item),
        "metrics": metrics,
        "per_item": per_item,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest_clinical.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(out, out_dir / "REPORT_CLINICAL.md")
    return out


def _write_report(out: dict, path: Path) -> None:
    m = out["metrics"]
    pc = m["type_accuracy_per_class"]
    lines = [
        "# MedGemma-4B — Clinical Image Intake Bench (SYNTHETIC)",
        "",
        f"- Generated: {out['generated_at']}  ·  Model: `{out['model']}`  ·  INT4 on RTX 4060",
        f"- {out['n_images']} images · **SYNTHETIC placeholders, no real pathology**",
        "",
        f"> ⚠️ **{out['warning']}**",
        "",
        "## Scored (what synthetic images can legitimately test)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Image-type accuracy (skin/eye/wound/oral) | {m['type_accuracy_overall']*100:.0f}% |",
        f"| — skin | {pc['skin']*100:.0f}% |",
        f"| — eye | {pc['eye']*100:.0f}% |",
        f"| — wound | {pc['wound']*100:.0f}% |",
        f"| — oral | {pc['oral']*100:.0f}% |",
        f"| Quality flag accuracy (usable/unusable) | {m['quality_accuracy']*100:.0f}% |",
        f"| Junk rejection (non-clinical → unknown/false) | {m['junk_rejection_rate']*100:.0f}% |",
        f"| Latency mean / p90 | {m['latency_s_mean']:.1f}s / {m['latency_s_p90']:.1f}s |",
        f"| VRAM peak | {m['vram_peak_mb']} MB |",
        "",
        "## NOT scored — clinical assessment probe",
        "The `assessment` text MedGemma produced per image is stored raw in "
        "`latest_clinical.json` for inspection ONLY. It is ungrounded (synthetic "
        "images have no pathology) and is deliberately not scored. It must not be "
        "presented as diagnostic capability, and emitting it in production would "
        "break the type+quality-only, never-diagnosis product invariant.",
        "",
        "## How to make this a REAL test",
        "1. Replace synthetic images with real, licensed, consented clinical photos "
        "with expert labels.",
        "2. Keep scoring to type + quality unless a clinician-validated diagnostic "
        "gold set and a governance decision on the no-diagnosis invariant exist.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _main(argv):
    p = argparse.ArgumentParser(description="MedGemma clinical-image bench (synthetic).")
    p.add_argument("--out", default=str(RESULTS_DIR))
    args = p.parse_args(argv)
    out = run(Path(args.out))
    m = out["metrics"]
    print(f"\nClinical bench complete (SYNTHETIC). Wrote latest_clinical.json, "
          f"REPORT_CLINICAL.md")
    print(f"  type_acc={m['type_accuracy_overall']*100:.0f}% "
          f"quality_acc={m['quality_accuracy']*100:.0f}% "
          f"junk_reject={m['junk_rejection_rate']*100:.0f}% "
          f"lat_mean={m['latency_s_mean']:.1f}s vram={m['vram_peak_mb']}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
