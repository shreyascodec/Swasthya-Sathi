"""Interpretation-layer bench: hand-curated table vs the LabQAR-550 table.

The interpretation stage is deterministic (lookup + numeric comparison, no
model), so the thing a bigger reference table changes is COVERAGE: how many
analytes on a real report can be resolved to a range at all, instead of coming
back `unknown / no_reference_range`.

Two measurements, neither circular:

  [A] COVERAGE — for a panel of analyte names as they appear on Indian lab
      reports, does the table resolve a usable interval? Ground truth is
      "a range exists", which is objective.

  [B] CORRECTNESS — a hand-verified case set where the expected status follows
      unambiguously from the interval the table itself reports (e.g. Hb 9.5
      against 12.0-17.0 must be `low`). This tests alias matching, unit
      handling, direction and critical thresholds — NOT the clinical validity
      of the ranges, which requires the clinician review pass.

Usage:
    python -m bench.runner_interpret
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from stages.interpret_rules import interpret_value, load_reference_table

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "bench" / "results_interpret"
CURATED = ROOT / "data" / "labqar" / "reference_ranges.yaml"
LABQAR = ROOT / "data" / "labqar" / "reference_ranges_labqar.yaml"

# [A] Analyte names as printed on common Indian lab reports (CBC, LFT, KFT,
# lipid, thyroid, diabetes, vitamins, cardiac, inflammatory, coagulation).
PANEL = [
    "Hemoglobin", "WBC", "Platelets", "Hematocrit", "MCV", "MCH", "MCHC", "RDW",
    "Neutrophils", "Lymphocytes", "Eosinophils", "Monocytes", "ESR", "Reticulocytes",
    "Glucose Fasting", "HbA1c", "Insulin", "C-peptide",
    "Creatinine", "Urea", "Uric acid", "Sodium", "Potassium", "Chloride", "Calcium",
    "Phosphorus", "Magnesium", "Bicarbonate",
    "Bilirubin Total", "SGPT", "SGOT", "Alkaline phosphatase", "Albumin",
    "Total protein", "Globulin", "Gamma glutamyl transferase",
    "Total Cholesterol", "Triglycerides", "HDL cholesterol", "LDL cholesterol",
    "TSH", "Free T4", "Free T3", "Thyroglobulin",
    "Vitamin D", "Vitamin B12", "Folate", "Ferritin", "Iron", "Transferrin",
    "C-reactive protein", "Troponin I", "Creatine kinase", "Lactate dehydrogenase",
    "Amylase", "Lipase", "Prothrombin time", "Fibrinogen", "D-dimer",
    "Prostate specific antigen", "Cortisol", "Testosterone", "Prolactin",
]

# [B] Hand-verified cases. `expect` follows from the resolved interval; cases
# marked expect=None only assert "not a crash / a defined status".
CASES = [
    # analyte, value, unit, printed_ref, sex, expected_status
    ("Hemoglobin", "9.5", "g/dL", "13.0-17.0", "female", "low"),
    ("Hemoglobin", "14.0", "g/dL", "13.0-17.0", "male", "normal"),
    ("Hemoglobin", "6.5", "g/dL", "13.0-17.0", "female", "critical"),   # curated panic
    ("Hb", "9.5", "g/dL", None, "female", "low"),                       # alias
    ("WBC", "11200", "/cumm", "4000-11000", None, "high"),
    ("Total leucocyte count", "8000", "/cumm", None, None, "normal"),   # alias
    ("Platelets", "1.4", "lakhs/cumm", "1.5-4.1", None, "low"),
    ("Glucose Fasting", "180", "mg/dL", "70-100", None, "high"),
    ("HbA1c", "5.2", "%", "4.0-5.6", None, "normal"),
    ("Creatinine", "2.4", "mg/dL", "0.7-1.3", None, "high"),
    ("TSH", "25.0", "mIU/L", "0.4-4.0", None, "critical"),              # curated panic
    ("Vitamin D", "12", "ng/mL", "30-100", None, "low"),
    ("Vitamin B12", "150", "pg/mL", "200-900", None, "low"),
    ("SGPT", "88", "U/L", "0-45", None, "high"),
    ("Triglycerides", "260", "mg/dL", "0-150", None, "high"),
    ("Bilirubin Total", "0.8", "mg/dL", "0.3-1.2", None, "normal"),
    ("Ferritin", "18", "ng/mL", "30-400", None, "low"),
    ("Urea", "60", "mg/dL", "15-40", None, "high"),
    # Analytes absent from the 15-row curated table (LabQAR should resolve these):
    ("Uric acid", "9.2", "mg/dL", None, "male", None),
    ("Albumin", "3.0", "g/dL", None, None, None),
    ("Sodium", "128", "mEq/L", None, None, None),
    ("Potassium", "6.2", "mEq/L", None, None, None),
    ("Calcium", "8.0", "mg/dL", None, None, None),
    ("Amylase", "300", "U/L", None, None, None),
    ("C-reactive protein", "45", "mg/L", None, None, None),
    ("Prolactin", "80", "ng/mL", None, "female", None),
    # Robustness: must fail safe, never guess.
    ("Hemoglobin", "not-a-number", "g/dL", None, None, "unknown"),
    ("Zzz Unknown Analyte", "5", "mg/dL", None, None, "unknown"),
]

DEFINITE = ("low", "normal", "high", "critical")


def eval_table(path: Path, label: str) -> dict:
    table = load_reference_table(path)
    # [A] coverage
    resolved, missing = [], []
    for name in PANEL:
        r = interpret_value(name, "1", None, None, table)
        # A usable range means we did not bail out with no_reference_range.
        (resolved if r.review_reason != "no_reference_range" else missing).append(name)

    # [B] correctness
    cases, correct, graded = [], 0, 0
    for analyte, value, unit, ref, sex, expect in CASES:
        got = interpret_value(analyte, value, unit, ref, table, sex=sex)
        row = {"analyte": analyte, "value": value, "sex": sex, "expected": expect,
               "status": got.status, "ref_used": got.ref_range,
               "needs_review": got.needs_review, "reason": got.review_reason}
        if expect is not None:
            graded += 1
            row["pass"] = got.status == expect
            correct += bool(row["pass"])
        else:
            # Ungraded: success = produced a definite status without review.
            row["pass"] = got.status in DEFINITE and not got.needs_review
        cases.append(row)

    definite = sum(1 for c in cases if c["status"] in DEFINITE)
    return {
        "table": label,
        "path": str(path),
        "version": table.version,
        "analytes_in_table": len(set(id(v) for v in table.by_alias.values())),
        "alias_keys": len(table.by_alias),
        "panel_size": len(PANEL),
        "panel_resolved": len(resolved),
        "panel_coverage": round(len(resolved) / len(PANEL), 4),
        "panel_missing": missing,
        "graded_cases": graded,
        "graded_correct": correct,
        "graded_accuracy": round(correct / graded, 4) if graded else None,
        "cases_definite_status": definite,
        "cases_total": len(cases),
        "cases": cases,
    }


def main() -> int:
    results = [eval_table(CURATED, "curated-15 (baseline)"),
               eval_table(LABQAR, "labqar-550 (new)")]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "results": results}
    (OUT_DIR / "latest_interpret.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md = ["# Interpretation layer — reference table comparison", "",
          f"generated: {payload['generated_at']}", "",
          "| table | version | analytes | panel coverage | graded accuracy | definite statuses |",
          "|---|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['table']} | `{r['version']}` | {r['analytes_in_table']} "
                  f"| {r['panel_resolved']}/{r['panel_size']} ({r['panel_coverage']:.0%}) "
                  f"| {r['graded_correct']}/{r['graded_cases']} ({r['graded_accuracy']:.0%}) "
                  f"| {r['cases_definite_status']}/{r['cases_total']} |")
    for r in results:
        md += ["", f"## {r['table']} — unresolved panel analytes ({len(r['panel_missing'])})",
               "", ", ".join(r["panel_missing"]) or "_none_"]
    fails = [c for c in results[-1]["cases"] if c.get("pass") is False]
    md += ["", "## Failing/unresolved cases on the new table", ""]
    md += ([f"- `{c['analyte']}` {c['value']}: expected {c['expected']}, got "
            f"{c['status']} ({c['reason'] or 'ok'})" for c in fails] or ["_none_"])
    (OUT_DIR / "REPORT_INTERPRET.md").write_text("\n".join(md), encoding="utf-8")

    for r in results:
        print(f"{r['table']:24s} analytes={r['analytes_in_table']:4d} "
              f"coverage={r['panel_coverage']:.0%} "
              f"graded={r['graded_correct']}/{r['graded_cases']} "
              f"definite={r['cases_definite_status']}/{r['cases_total']}")
    print(f"\nwrote {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
