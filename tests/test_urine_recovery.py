"""Urine albumin/protein recovery (Stage 5).

The numeric OCR field extractor drops a unit-less qualitative value like
"Urine Albumin ++", so proteinuria — a pre-eclampsia component — never reached
the maternal risk engine or the intake questions, even though OCR raw_text had
it verbatim. Stage 5 recovers the grade deterministically in maternal mode.
"""

from __future__ import annotations

import re

from core.context import OCRResult, SessionContext
from stages.maternal_risk import assess_maternal_risk
from stages.s5_interpret import InterpretStage

RE = InterpretStage._URINE_PROTEIN_RE


def test_regex_grades():
    cases = {
        "Urine Albumin ++ Nil H": "++",
        "Urine Albumin 3+ Nil": "3+",
        "Urine Protein: Trace": "Trace",
        "Urine Albumin Nil": "Nil",
    }
    for line, want in cases.items():
        m = RE.search(line)
        assert m and re.sub(r"\s+", "", m.group(1)) == want, line


def test_regex_ignores_non_matches():
    # Urine SUGAR is not albumin/protein; the sample-type line mentions urine but
    # not a grade — neither must match.
    assert RE.search("Urine Sugar Nil Nil") is None
    assert RE.search("EDTA Blood + Serum + Urine SHC-260921-1187") is None


def _stage():
    # Bypass __init__ (needs config/models); the method only uses the class regex.
    return object.__new__(InterpretStage)


def test_recovery_injects_finding():
    ctx = SessionContext(session_id="u1", lang="en")
    ctx.ocr = OCRResult(raw_text="VITALS\nURINE ROUTINE\nUrine Albumin ++ Nil H\nUrine Sugar Nil")
    out = _stage()._recover_urine_protein(ctx, [{"analyte": "Hemoglobin", "value": "10.4"}])
    urine = [f for f in out if f["analyte"] == "Urine Protein"]
    assert urine and urine[0]["value"] == "++"


def test_recovery_noop_when_already_present():
    ctx = SessionContext(session_id="u2", lang="en")
    ctx.ocr = OCRResult(raw_text="Urine Albumin ++ Nil H")
    existing = [{"analyte": "Urine Albumin", "value": "++"}]
    out = _stage()._recover_urine_protein(ctx, existing)
    assert out == existing  # not duplicated


def test_recovery_noop_when_absent():
    ctx = SessionContext(session_id="u3", lang="en")
    ctx.ocr = OCRResult(raw_text="Hemoglobin 10.4 g/dL\nPlatelets 1.4 lakhs")
    out = _stage()._recover_urine_protein(ctx, [])
    assert out == []


def test_recovered_proteinuria_drives_high_tier():
    # High BP + recovered proteinuria "++" -> Pre-eclampsia (R005) -> HIGH.
    findings = [
        {"analyte": "Blood Pressure", "value": "158/104", "unit": "mmHg"},
        {"analyte": "Urine Protein", "value": "++", "unit": "", "ref_range": "Nil"},
    ]
    interps = [{"analyte": "Blood Pressure", "value": "158/104", "unit": "mmHg", "status": "unknown"}]
    r = assess_maternal_risk(findings, interps)
    assert r["tier"] == "high"
    assert "R005" in {x["id"] for x in r["pmsma_rules"]}
