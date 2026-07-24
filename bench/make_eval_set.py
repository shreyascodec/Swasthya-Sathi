"""Generate the synthetic Hindi+English evaluation set for the summary bake-off.

Each item carries OCR fields (the model's only source of truth) and a GOLD
structured summary derived from the same facts, so extraction accuracy and
faithfulness are well-defined. Replace/extend with real clinician-labeled
reports later — the format is stable.

Run:  python -m bench.make_eval_set
Writes: data/eval/eval_set.json
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "eval" / "eval_set.json"

# (analyte, value, unit, ref_range)
_PANELS = [
    [("Hemoglobin", "9.5", "g/dL", "13.0-17.0"),
     ("WBC", "11200", "/cumm", "4000-11000"),
     ("Platelets", "1.4", "lakhs/cumm", "1.5-4.1")],
    [("Glucose Fasting", "142", "mg/dL", "70-100"),
     ("HbA1c", "7.8", "%", "4.0-5.6")],
    [("Creatinine", "1.6", "mg/dL", "0.7-1.3"),
     ("Urea", "48", "mg/dL", "15-40")],
    [("TSH", "6.9", "mIU/L", "0.4-4.0"),
     ("Vitamin D", "18", "ng/mL", "30-100")],
    [("Total Cholesterol", "232", "mg/dL", "125-200"),
     ("Triglycerides", "210", "mg/dL", "0-150")],
    [("Bilirubin Total", "2.1", "mg/dL", "0.3-1.2"),
     ("SGPT", "68", "U/L", "0-45")],
    [("Hemoglobin", "14.2", "g/dL", "13.0-17.0"),
     ("Glucose Fasting", "92", "mg/dL", "70-100")],
    [("Vitamin B12", "180", "pg/mL", "200-900"),
     ("Ferritin", "12", "ng/mL", "30-400")],
]

_FACILITIES = [
    "Apollo Diagnostic Centre", "City Care Laboratory", "Sanjeevani Pathology Lab",
    "Metro Hospital Lab", "Lifeline Diagnostics", "Arogya Clinic Laboratory",
    "Sunrise Medical Centre", "Nova Path Labs",
]
_DOCTORS = [
    "Dr. A K Sharma", "Dr. Priya Nair", "Dr. R Mehta", "Dr. S Iyer",
    "Dr. Kavita Rao", "Dr. M Khan", "Dr. Anil Gupta", "Dr. Neha Verma",
]
_DATES = [
    "12/05/2026", "03/06/2026", "21/04/2026", "09/06/2026",
    "17/03/2026", "28/05/2026", "02/06/2026", "14/05/2026",
]
_DRUGS = [None, "Tab Metformin 500mg", None, "Tab Thyronorm 50mcg",
          "Tab Atorvastatin 10mg", None, None, "Cap Vitamin B12"]


def build_items() -> list[dict]:
    items: list[dict] = []
    for i, panel in enumerate(_PANELS):
        for lang in ("en", "hi"):
            fields: list[dict] = []
            gold_findings: list[dict] = []
            for analyte, value, unit, ref in panel:
                low_conf = (analyte == "WBC")  # simulate one hard-to-read field
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

            items.append({
                "id": f"rpt_{i:02d}_{lang}",
                "lang": lang,
                "ocr_fields": fields,
                "gold": {
                    "facility": _FACILITIES[i],
                    "doctor": _DOCTORS[i],
                    "report_dates": [_DATES[i]],
                    "lab_findings": gold_findings,
                    "medications": gold_meds,
                },
            })
    return items


def main() -> None:
    items = build_items()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    langs = {}
    for it in items:
        langs[it["lang"]] = langs.get(it["lang"], 0) + 1
    print(f"Wrote {len(items)} eval items to {OUT} ({langs})")


if __name__ == "__main__":
    main()
