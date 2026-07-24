"""Phase 2 acceptance tests (PLAN.md Phase 2).

Covers the deterministic field extractor, the OCRStage end-to-end via the
stub engine (config-swappable, no heavy deps), low-confidence flagging, the
ModelManager load-on-entry / unload-on-exit seam, and PDF text-layer intake.

Real PaddleOCR vs Surya accuracy (>=90%) needs real report samples and is
benched later; here we prove the pipeline, contracts, and extraction logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import models  # noqa: F401  (register adapters)
from core.context import SessionContext, UploadedFile
from core.pipeline import Pipeline
from models.ocr_base import OCRToken
from stages.ocr_extract import extract_fields


# --- field extractor (pure) --------------------------------------------------
def test_extract_lab_values_units_and_ranges() -> None:
    text = (
        "City Diagnostic Laboratory\n"
        "Dr. A K Sharma\n"
        "Hemoglobin 13.5 g/dL (13.0-17.0)\n"
        "Glucose 210 mg/dL\n"
        "Report date 12/05/2026\n"
    )
    tokens = [
        OCRToken("City Diagnostic Laboratory", 0.97),
        OCRToken("Dr. A K Sharma", 0.60),
        OCRToken("Hemoglobin 13.5 g/dL (13.0-17.0)", 0.95),
        OCRToken("Glucose 210 mg/dL", 0.55),
        OCRToken("Report date 12/05/2026", 0.90),
    ]
    fields = extract_fields(text, tokens, low_confidence_threshold=0.80)
    by_name = {f.name.lower(): f for f in fields}

    assert "hemoglobin" in by_name
    assert by_name["hemoglobin"].value == "13.5"
    assert by_name["hemoglobin"].unit == "g/dL"
    assert by_name["hemoglobin"].low_confidence is False

    assert any("ref-range" in n and by_name[n].value == "13.0-17.0" for n in by_name)

    assert "glucose" in by_name
    assert by_name["glucose"].low_confidence is True   # 0.55 < 0.80

    assert any(f.name == "date" and f.value == "12/05/2026" for f in fields)
    assert any(f.name == "doctor" for f in fields)
    assert any(f.name == "facility" for f in fields)


def test_extract_drugs() -> None:
    text = "Tab Metformin 500mg twice daily\nCap Amoxicillin 250mg"
    fields = extract_fields(text, [], 0.8)
    assert sum(1 for f in fields if f.name == "drug") >= 1


# --- horizontal "ANALYTE VALUE [unit] LOW-HIGH" rows --------------------------
# Regression guard for a WRONG-VALUE defect, not merely a coverage gap: both
# _VALUE_RE and _KV_EOL_RE are unanchored/end-anchored, so on a row whose value
# is not followed by a RECOGNIZED unit they matched the trailing reference range
# and reported its HIGH BOUND as the measurement. Observed on the real bench
# reports: Transferrin Saturation 12.45 (a LOW value) was reported as 50
# (normal), Direct Bilirubin 0.10 as 0.40, A/G Ratio 1.48 as 2.5.

@pytest.mark.parametrize(
    "line,name,value",
    [
        # OCR-corrupted unit ("mg/dIl") -> _VALUE_RE cannot see it
        ("Direct Bilirubin 0.10 mg/dIl 0-0.40 mg/dl", "Direct Bilirubin", "0.10"),
        # no unit at all between value and range
        ("Transferin Saturation 12.45 20-50%", "Transferin Saturation", "12.45"),
        ("A/G Ratio 1.48 1.0-2.5", "A/G Ratio", "1.48"),
        ("Specific Gravity 1.020 1.005-1.030", "Specific Gravity", "1.020"),
        # recognized unit present — must keep working
        ("Eosoniphils 3 % 1-7%", "Eosoniphils", "3"),
        ("Serum Sodium 134.9 mEq/L 136-145 mEq/L", "Serum Sodium", "134.9"),
        ("Blood Urea  33.65 mg/dl 0-48.0 mg/dl", "Blood Urea", "33.65"),
        ("Packed Cell Volume (PCV) 38.9 % 37.0-54.0 %", "Packed Cell Volume (PCV)", "38.9"),
    ],
)
def test_horizontal_row_takes_value_not_range_bound(line, name, value) -> None:
    fields = [f for f in extract_fields(line, [], 0.8) if not f.name.endswith("ref-range")]
    got = {f.name: f.value for f in fields}
    assert got.get(name) == value, f"{line!r} -> {got}"


@pytest.mark.parametrize(
    "line",
    [
        # OCR lost the measurement; only the range survived. Inventing a value
        # out of a range bound is worse than extracting nothing.
        "Globulin g/dl 2.3-3.5 g/dl",
        # the range IS the finding (urine microscopy), not a measurement
        "EPITHELIAL CELLS 2-3",
    ],
)
def test_range_only_row_yields_no_value(line) -> None:
    fields = [f for f in extract_fields(line, [], 0.8) if not f.name.endswith("ref-range")]
    assert fields == [], f"{line!r} -> {[(f.name, f.value) for f in fields]}"


def test_parenthesised_range_still_parsed() -> None:
    """The value precedes the range, so position-based rejection must not fire."""
    fields = extract_fields("Hemoglobin 13.5 g/dL (13.0-17.0)", [], 0.8)
    by_name = {f.name.lower(): f for f in fields}
    assert by_name["hemoglobin"].value == "13.5"
    assert any("ref-range" in n and by_name[n].value == "13.0-17.0" for n in by_name)


def test_unitless_eol_row_still_parsed() -> None:
    """Ophthalmic-style rows have no range tail and must keep extracting."""
    fields = extract_fields("CDR 0.42\nVDD 1.73", [], 0.8)
    got = {f.name: f.value for f in fields}
    assert got.get("CDR") == "0.42" and got.get("VDD") == "1.73"


# --- OCRStage end-to-end via stub engine -------------------------------------
def _stub_pipeline() -> Pipeline:
    p = Pipeline(env_name="dev_4060")
    p.config.models["ocr"]["primary"]["impl"] = "stub_ocr"   # bench-swap by config
    p.config.models["ocr"]["primary"]["device"] = "cpu"
    return p


def test_ocr_stage_end_to_end_and_unloads(tmp_path: Path) -> None:
    source = tmp_path / "report1.dat"     # not an image; stub uses the sidecar
    source.write_text("placeholder", encoding="utf-8")
    sidecar = Path(str(source) + ".ocr.json")
    sidecar.write_text(json.dumps({
        "tokens": [
            {"text": "Apollo Diagnostic Centre", "confidence": 0.98},
            {"text": "Hemoglobin 9.5 g/dL (13.0-17.0)", "confidence": 0.93},
            {"text": "Glucose 210 mg/dL", "confidence": 0.52},
            {"text": "Date 12/05/2026", "confidence": 0.9},
        ]
    }), encoding="utf-8")

    pipeline = _stub_pipeline()
    ctx = SessionContext(session_id="p2test01", lang="hi")
    ctx.uploads.append(
        UploadedFile(id="u0", path=str(source), source_path=str(source), type="image")
    )

    ctx = pipeline.run_stage("ocr", ctx)

    assert ctx.ocr is not None
    assert ctx.ocr.engine == "stub_ocr"
    names = {f.name.lower() for f in ctx.ocr.fields}
    assert "hemoglobin" in names and "glucose" in names
    assert any(f.name.lower() == "glucose" and f.low_confidence for f in ctx.ocr.fields)
    assert any(e.action == "stage.ocr.done" for e in ctx.audit)

    # load-on-entry / unload-on-exit: engine released, VRAM seam clean.
    assert "ocr" not in pipeline.models.loaded


def test_ocr_stage_reads_pdf_text_layer(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hemoglobin 13.5 g/dL")
    page.insert_text((72, 100), "Glucose 95 mg/dL")
    doc.save(str(pdf_path))
    doc.close()

    pipeline = _stub_pipeline()
    ctx = SessionContext(session_id="p2test02", lang="hi")
    ctx.uploads.append(
        UploadedFile(id="u0", path=str(pdf_path), source_path=str(pdf_path), type="pdf")
    )

    ctx = pipeline.run_stage("ocr", ctx)
    names = {f.name.lower() for f in ctx.ocr.fields}
    assert "hemoglobin" in names and "glucose" in names


@pytest.mark.parametrize(
    "line,analyte,value,ref",
    [
        # Slash-first counted units. _UNIT_LOOSE required a leading letter, so
        # "/cumm" could not match: the label backtracked to swallow
        # "WBC 11200 /cumm" and the range split into value "400" + "0-11000",
        # INVENTING 400 and losing a genuinely high WBC. Caught end-to-end on a
        # real 3-page report where the abnormal WBC never reached interpret.
        ("WBC 11200 /cumm 4000-11000", "WBC", "11200", "4000-11000"),
        ("TLC 11200 /cumm 4000-11000", "TLC", "11200", "4000-11000"),
        # Letter-first unit on the same shape always worked; keep it that way.
        ("WBC 11200 cells/cumm 4000-11000", "WBC", "11200", "4000-11000"),
    ],
)
def test_slash_first_unit_does_not_eat_the_value(line, analyte, value, ref) -> None:
    fields = {f.name: f for f in extract_fields(line)}
    assert analyte in fields, f"{analyte!r} not extracted from {line!r}: {list(fields)}"
    assert fields[analyte].value == value
    assert fields[f"{analyte} ref-range"].value == ref


def test_decimal_still_not_split_by_loose_unit() -> None:
    """The '.'-exclusion that _UNIT_LOOSE was written for must survive.

    Allowing '/' to start a unit must not re-open splitting "2.3" into
    value "2" + unit "." + range "3-3.5".
    """
    fields = {f.name: f for f in extract_fields("Serum Albumin 2.3 3-3.5 g/dl")}
    assert fields["Serum Albumin"].value == "2.3"
    assert fields["Serum Albumin ref-range"].value == "3-3.5"
