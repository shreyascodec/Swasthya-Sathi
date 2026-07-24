"""Generate the MULTI-REPORT evaluation set for the summary bake-off.

Unlike make_eval_set.py (one panel = one item), each item here BUNDLES several
report pages (different facilities / dates / panels) into a SINGLE summarization
call. This measures what actually happens at the kiosk: a patient hands over a
small stack of pages and expects ONE consolidated summary.

For every page we also render a realistic lab-report PNG under data/eval/pages/,
so the same items can be run text-only OR multimodal (text + page images) —
the multimodal MedGemma path consumes these images.

Run:  python -m bench.make_eval_multi
Writes: data/eval/eval_set_multi.json  +  data/eval/pages/<item>_p<k>.png
"""

from __future__ import annotations

import json
from pathlib import Path

from bench.make_eval_set import (
    _DATES, _DOCTORS, _DRUGS, _FACILITIES, _PANELS,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval" / "eval_set_multi.json"
PAGES_DIR = ROOT / "data" / "eval" / "pages"

# How the 8 single panels are grouped into multi-page bundles.
# Mix of 2- and 3-page stacks so we cover both ends of a realistic visit.
_BUNDLES = [
    [0, 1, 2],   # 3 pages: CBC + diabetes + renal
    [3, 4],      # 2 pages: thyroid/vitD + lipid
    [5, 6, 7],   # 3 pages: LFT + normal CBC + B12/ferritin
]


def _page_fields(i: int) -> tuple[list[dict], dict]:
    """OCR fields + gold for a single source page (mirrors make_eval_set)."""
    panel = _PANELS[i]
    fields: list[dict] = []
    gold_findings: list[dict] = []
    for j, (analyte, value, unit, ref) in enumerate(panel):
        # Simulate OCR degradation: the first analyte of every page, plus any WBC
        # (a chronically hard-to-read field), come back low-confidence. Their true
        # value is still legible in the rendered page image, so the multimodal run
        # can recover it — that is the vision_recovery test.
        low_conf = (j == 0) or (analyte == "WBC")
        fields.append({"name": analyte, "value": value, "unit": unit,
                       "low_confidence": low_conf})
        fields.append({"name": f"{analyte} ref-range", "value": ref,
                       "unit": unit, "low_confidence": False})
        gold_findings.append({"analyte": analyte, "value": value, "unit": unit,
                              "ref_range": ref, "source_field": analyte})
    fields.append({"name": "facility", "value": _FACILITIES[i], "unit": None,
                   "low_confidence": False})
    fields.append({"name": "doctor", "value": _DOCTORS[i], "unit": None,
                   "low_confidence": False})
    fields.append({"name": "date", "value": _DATES[i], "unit": None,
                   "low_confidence": False})
    gold_meds = []
    if _DRUGS[i]:
        fields.append({"name": "drug", "value": _DRUGS[i], "unit": None,
                       "low_confidence": False})
        gold_meds.append({"name": _DRUGS[i], "source_field": "drug"})
    gold = {
        "facility": _FACILITIES[i],
        "doctor": _DOCTORS[i],
        "report_dates": [_DATES[i]],
        "lab_findings": gold_findings,
        "medications": gold_meds,
    }
    return fields, gold


def _render_page(fields: list[dict], panel_idx: int, page_no: int, out_path: Path) -> None:
    """Render a plain but realistic lab-report page as a PNG (for the VLM path)."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1000, 1400
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def font(size: int, bold: bool = False):
        candidates = (["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"])
        for name in candidates:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    f_title = font(40, bold=True)
    f_h = font(24, bold=True)
    f = font(24)
    f_small = font(20)

    by_name = {x["name"]: x for x in fields}
    facility = by_name.get("facility", {}).get("value", "")
    doctor = by_name.get("doctor", {}).get("value", "")
    date = by_name.get("date", {}).get("value", "")

    # Header
    d.rectangle([0, 0, W, 130], fill="#123f5e")
    d.text((40, 30), facility, font=f_title, fill="white")
    d.text((40, 88), "LABORATORY INVESTIGATION REPORT", font=f_small, fill="#cfe3f2")

    y = 160
    d.text((40, y), f"Referring Physician: {doctor}", font=f, fill="black"); y += 36
    d.text((40, y), f"Report Date: {date}", font=f, fill="black"); y += 36
    d.text((40, y), f"Page {page_no}", font=f_small, fill="#666666"); y += 50

    # Table header
    cols = [40, 430, 620, 800]
    d.line([(40, y), (W - 40, y)], fill="#123f5e", width=2)
    y += 10
    d.text((cols[0], y), "Test", font=f_h, fill="#123f5e")
    d.text((cols[1], y), "Result", font=f_h, fill="#123f5e")
    d.text((cols[2], y), "Unit", font=f_h, fill="#123f5e")
    d.text((cols[3], y), "Ref. Range", font=f_h, fill="#123f5e")
    y += 40
    d.line([(40, y), (W - 40, y)], fill="#123f5e", width=2)
    y += 20

    for analyte, value, unit, ref in _PANELS[panel_idx]:
        d.text((cols[0], y), analyte, font=f, fill="black")
        d.text((cols[1], y), value, font=f, fill="black")
        d.text((cols[2], y), unit or "", font=f, fill="black")
        d.text((cols[3], y), ref, font=f_small, fill="#444444")
        y += 44

    # Medication line, if any
    drug = by_name.get("drug", {}).get("value")
    if drug:
        y += 30
        d.text((40, y), f"Advice / Medication: {drug}", font=f, fill="black")

    # Footer
    d.line([(40, H - 90), (W - 40, H - 90)], fill="#cccccc", width=1)
    d.text((40, H - 70), "This is a computer-generated report for POC evaluation.",
           font=f_small, fill="#888888")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def build_items() -> list[dict]:
    items: list[dict] = []
    for b, panel_idxs in enumerate(_BUNDLES):
        for lang in ("en", "hi"):
            item_id = f"multi_{b:02d}_{lang}"
            all_fields: list[dict] = []
            page_images: list[str] = []
            merged = {
                "facility": None, "doctor": None, "report_dates": [],
                "lab_findings": [], "medications": [],
                "facilities": [], "doctors": [],
            }
            for page_no, pidx in enumerate(panel_idxs, start=1):
                fields, gold = _page_fields(pidx)
                all_fields.extend(fields)
                merged["lab_findings"].extend(gold["lab_findings"])
                merged["medications"].extend(gold["medications"])
                merged["report_dates"].extend(gold["report_dates"])
                merged["facilities"].append(gold["facility"])
                merged["doctors"].append(gold["doctor"])

                # Render the page image once (language-independent layout; the
                # en/hi items share panels but get their own copy for clarity).
                png = PAGES_DIR / f"{item_id}_p{page_no}.png"
                _render_page(fields, pidx, page_no, png)
                page_images.append(str(png.relative_to(ROOT)).replace("\\", "/"))

            merged["facility"] = merged["facilities"][0]
            merged["doctor"] = merged["doctors"][0]

            items.append({
                "id": item_id,
                "lang": lang,
                "n_pages": len(panel_idxs),
                "ocr_fields": all_fields,
                "page_images": page_images,
                "gold": merged,
            })
    return items


def main() -> None:
    items = build_items()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    langs: dict[str, int] = {}
    pages = 0
    for it in items:
        langs[it["lang"]] = langs.get(it["lang"], 0) + 1
        pages += it["n_pages"]
    print(f"Wrote {len(items)} multi-report items ({langs}), "
          f"{pages} rendered pages total -> {OUT}")
    print(f"Page PNGs under {PAGES_DIR}")


if __name__ == "__main__":
    main()
