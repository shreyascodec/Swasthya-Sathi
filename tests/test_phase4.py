"""Phase 4 acceptance tests (PLAN.md Phase 4).

Covers structured-schema fill from OCR, the FAITHFULNESS gate (a test that fails
if the summary contains a value not present in OCR — the required guardrail),
the drop-hallucinations behaviour, the stage end-to-end via the stub LLM with
load/unload, and the bake-off harness metrics + runner over the eval set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import models  # noqa: F401  (register adapters)
from bench.dataset import load_eval_set
from bench.metrics import extraction_prf, hindi_quality
from bench.runner import run as run_bench
from core.context import OCRField, OCRResult, SessionContext
from core.pipeline import Pipeline
from stages.faithfulness import (
    check_faithfulness, drop_hallucinations, reconcile_multimodal,
)
from stages.summary_schema import LabFinding, SummarySchema


def _ocr_fields() -> list[OCRField]:
    return [
        OCRField(name="Hemoglobin", value="9.5", unit="g/dL"),
        OCRField(name="Hemoglobin ref-range", value="13.0-17.0", unit="g/dL"),
        OCRField(name="Glucose", value="142", unit="mg/dL"),
        OCRField(name="facility", value="Apollo Diagnostic Centre"),
        OCRField(name="date", value="12/05/2026"),
    ]


def _ctx_with_ocr(lang: str = "hi") -> SessionContext:
    ctx = SessionContext(session_id="p4test", lang=lang)
    ctx.ocr = OCRResult(raw_text="", fields=_ocr_fields(), engine="stub_ocr")
    return ctx


def _stub_pipeline() -> Pipeline:
    p = Pipeline(env_name="dev_4060")
    p.config.models["llm"]["primary"] = {"impl": "stub_llm", "device": "cpu"}
    return p


# --- value<->analyte binding (adversarial) ------------------------------------
# These encode hallucination classes that the ORIGINAL numeric gate accepted at
# faithfulness=1.00, because it asked "does this number appear anywhere on the
# report?" rather than "does this number belong to THIS analyte?". On a real
# multi-page session the global number pool is large enough that almost any
# plausible value passes. See nlp-robustness.md section 1.
#
# They are written as the SPECIFICATION of what must never pass.

def _bind_fields() -> list[OCRField]:
    return [
        OCRField(name="Hemoglobin", value="13.5", unit="g/dL"),
        OCRField(name="Potassium", value="4.63", unit="mEq/L"),
        OCRField(name="Creatinine", value="1.40", unit="mg/dL"),
    ]


def test_value_from_another_analyte_is_rejected() -> None:
    """Potassium's value attached to Hemoglobin = fabricated severe anemia."""
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Hemoglobin", "value": "4.63", "unit": "g/dL",
         "source_field": "Hemoglobin"}]})
    report = check_faithfulness(s, _bind_fields())
    assert not report.ok, "value/analyte swap accepted"
    assert any(i.kind == "value_analyte_mismatch" for i in report.issues)


def test_invented_analyte_reusing_existing_number_is_rejected() -> None:
    """Creatinine's number on a cardiac marker that is not on the report."""
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Troponin I", "value": "1.40", "unit": "ng/mL",
         "source_field": "Creatinine"}]})
    report = check_faithfulness(s, _bind_fields())
    assert not report.ok, "invented analyte accepted"


def test_wrong_unit_is_flagged() -> None:
    """13.5 mg/dL for hemoglobin is a 1000x scale error, not a typo."""
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Hemoglobin", "value": "13.5", "unit": "mg/dL",
         "source_field": "Hemoglobin"}]})
    report = check_faithfulness(s, _bind_fields())
    assert not report.ok, "unit mismatch accepted"
    assert any(i.kind == "unit_mismatch" for i in report.issues)


def test_correctly_bound_finding_still_passes() -> None:
    """The guard must not reject legitimate findings."""
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Hemoglobin", "value": "13.5", "unit": "g/dL",
         "source_field": "Hemoglobin"}]})
    report = check_faithfulness(s, _bind_fields())
    assert report.ok, [i.kind + ":" + i.detail for i in report.issues]


def test_binding_tolerates_ocr_name_variants() -> None:
    """'Serum Sodium' on the report vs 'Sodium' in the summary is the SAME
    analyte — normalization must bridge it or every real session breaks."""
    fields = [OCRField(name="Serum Sodium", value="134.9", unit="mEq/L")]
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Sodium", "value": "134.9", "unit": "mEq/L",
         "source_field": "Serum Sodium"}]})
    report = check_faithfulness(s, fields)
    assert report.ok, [i.kind + ":" + i.detail for i in report.issues]


@pytest.mark.parametrize(
    "ocr_name,summary_name",
    [
        # An LLM rewrites analytes to their canonical name. These are SYNONYMS,
        # not different analytes — rejecting them broke 18 of 63 legitimate
        # findings on the real bench reports before the reference table was used
        # as the synonym authority.
        ("Haemoglobin", "Hemoglobin"),
        ("Packed Cell Volume (PCV)", "Hematocrit"),
        ("S.G.O.T", "Aspartate aminotransferase (AST, SGOT)"),
        ("R.B.C. Count", "Red blood cell count"),
        ("HDL", "HDL Cholesterol"),
        ("IONIC CALCIUM", "Ionized calcium"),
    ],
)
def test_synonym_analyte_names_bind(ocr_name, summary_name) -> None:
    fields = [OCRField(name=ocr_name, value="12.3", unit="g/dL")]
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": summary_name, "value": "12.3", "unit": "g/dL",
         "source_field": ocr_name}]})
    report = check_faithfulness(s, fields)
    assert report.ok, f"{ocr_name!r}/{summary_name!r}: {[i.detail for i in report.issues]}"


@pytest.mark.parametrize(
    "ocr_name,summary_name",
    [
        # Synonym resolution must NOT collapse clinically distinct analytes.
        ("Creatinine", "Urine Creatinine"),
        ("Total Cholesterol", "LDL Cholesterol"),
        ("Total Cholesterol", "HDL Cholesterol"),
        ("Bilirubin", "Direct Bilirubin"),
        ("Calcium", "Ionised Calcium"),
    ],
)
def test_distinct_analytes_never_bind(ocr_name, summary_name) -> None:
    fields = [OCRField(name=ocr_name, value="180", unit="mg/dL")]
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": summary_name, "value": "180", "unit": "mg/dL",
         "source_field": ocr_name}]})
    assert not check_faithfulness(s, fields).ok, \
        f"{summary_name!r} wrongly bound to {ocr_name!r}"


def test_drop_removes_misbound_finding() -> None:
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Hemoglobin", "value": "4.63", "unit": "g/dL",
         "source_field": "Hemoglobin"}]})
    cleaned = drop_hallucinations(s, _bind_fields())
    assert cleaned.lab_findings == []
    assert "Hemoglobin" in cleaned.unknowns


def test_medication_requires_token_match() -> None:
    """Substring matching traced a medication named 'm' to 'Tab Metformin'."""
    fields = [OCRField(name="drug", value="Tab Metformin 500mg")]
    s = SummarySchema.model_validate({"medications": [
        {"name": "m", "source_field": "drug"}]})
    assert not check_faithfulness(s, fields).ok, "single-letter medication traced"


def test_real_medication_still_traces() -> None:
    fields = [OCRField(name="drug", value="Tab Metformin 500mg")]
    s = SummarySchema.model_validate({"medications": [
        {"name": "Metformin", "source_field": "drug"}]})
    assert check_faithfulness(s, fields).ok


# --- faithfulness gate -------------------------------------------------------
def test_faithfulness_flags_hallucinated_value() -> None:
    fields = _ocr_fields()
    summary = SummarySchema(
        lab_findings=[
            LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL", source_field="Hemoglobin"),
            LabFinding(analyte="Cholesterol", value="999", unit="mg/dL", source_field="unknown"),
        ]
    )
    report = check_faithfulness(summary, fields)
    assert not report.ok
    assert report.faithfulness < 1.0
    assert any(i.kind == "hallucinated_value" for i in report.issues)


def test_faithful_summary_passes() -> None:
    fields = _ocr_fields()
    summary = SummarySchema(
        lab_findings=[LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL",
                                 source_field="Hemoglobin")]
    )
    assert check_faithfulness(summary, fields).faithfulness == 1.0


def test_parses_python_dict_literal_output() -> None:
    """Models intermittently emit a Python dict literal (single quotes, None)
    instead of JSON. Measured on a real report: the content was correct and
    complete, but json.loads failed and the whole summary was discarded."""
    from stages.summary_build import parse_summary

    raw = ("{'facility': None, 'doctor': 'Dr. X', "
           "'lab_findings': [{'analyte': 'HbA1c', 'value': '5.20', 'unit': '%'}], "
           "'narrative_en': 'Prose here.', 'unknowns': []}")
    parsed = parse_summary(raw)
    assert parsed["lab_findings"][0]["analyte"] == "HbA1c"
    assert parsed["narrative_en"] == "Prose here."
    # Proper JSON must still take the fast path unchanged.
    assert parse_summary('{"narrative_en": "y", "lab_findings": []}')["narrative_en"] == "y"


def test_bloated_source_field_is_truncated() -> None:
    """A model that echoes the input into source_field ate the token budget and
    the narrative vanished. Keep the leading name, drop the dump."""
    long_dump = 'page 0, fields [{"name": "Blood Urea", "value": "33.65"' + "x" * 300
    f = LabFinding(analyte="Blood Urea", value="33.65", source_field=long_dump)
    assert len(f.source_field) <= 120


def test_source_field_accepts_array_form() -> None:
    """A model may cite source_field as a JSON array (a value + its ref-range).

    Rejecting the array form failed validation for the WHOLE summary, silently
    emptying it — narrative, findings and all. Coerce to the declared string.
    """
    finding = LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL",
                         source_field=["Hemoglobin", "Hemoglobin ref-range"])
    assert finding.source_field == "Hemoglobin, Hemoglobin ref-range"
    assert LabFinding(analyte="X", value="1", source_field=[]).source_field == "unknown"


def test_multi_field_citation_is_not_a_bad_source() -> None:
    """Citing both the value field and its ref-range partner is BETTER
    provenance, not worse — it must not be reported as a bad source."""
    fields = _ocr_fields()
    summary = SummarySchema(
        lab_findings=[LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL",
                                 source_field="Hemoglobin, Hemoglobin ref-range")]
    )
    report = check_faithfulness(summary, fields)
    assert not any(i.kind == "bad_source" for i in report.issues)
    # ...but a genuinely missing field is still caught.
    bad = SummarySchema(
        lab_findings=[LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL",
                                 source_field="Hemoglobin, NoSuchField")]
    )
    assert any(i.kind == "bad_source" for i in check_faithfulness(bad, fields).issues)


def test_reconcile_multimodal_keeps_verified_moves_image_only() -> None:
    fields = _ocr_fields()  # has Hemoglobin, Glucose; NOT Platelets
    summary = SummarySchema(lab_findings=[
        LabFinding(analyte="Hemoglobin", value="9.5", source_field="Hemoglobin"),
        LabFinding(analyte="Platelets", value="1.4", unit="lakhs/cumm", source_field="image"),
    ])
    cleaned, unverified = reconcile_multimodal(summary, fields)
    analytes = {f.analyte for f in cleaned.lab_findings}
    assert "Hemoglobin" in analytes            # OCR-traced stays verified
    assert "Platelets" not in analytes         # image-only pulled out of findings
    assert check_faithfulness(cleaned, fields).ok  # stored findings stay faithful
    assert len(unverified) == 1
    assert unverified[0]["analyte"] == "Platelets"
    assert unverified[0]["needs_review"] is True and unverified[0]["source"] == "image"


def test_drop_hallucinations_removes_untraceable() -> None:
    fields = _ocr_fields()
    summary = SummarySchema(lab_findings=[
        LabFinding(analyte="Hemoglobin", value="9.5", source_field="Hemoglobin"),
        LabFinding(analyte="Cholesterol", value="999", source_field="unknown"),
    ])
    cleaned = drop_hallucinations(summary, fields)
    analytes = {f.analyte for f in cleaned.lab_findings}
    assert "Hemoglobin" in analytes
    assert "Cholesterol" not in analytes
    assert "Cholesterol" in cleaned.unknowns
    assert check_faithfulness(cleaned, fields).ok


# --- stage end-to-end via stub ----------------------------------------------
def test_summary_stage_fills_schema_and_unloads() -> None:
    pipeline = _stub_pipeline()
    ctx = pipeline.run_stage("summary", _ctx_with_ocr("hi"))

    assert ctx.summary is not None
    content = SummarySchema.model_validate(ctx.summary.content)
    analytes = {f.analyte.lower() for f in content.lab_findings}
    assert "hemoglobin" in analytes and "glucose" in analytes
    assert content.facility == "Apollo Diagnostic Centre"
    assert content.narrative_en  # English clinical narrative present
    assert "narrative_hi" not in ctx.summary.content  # summary is English-only
    # Stored summary is faithful by construction (gate applied).
    assert check_faithfulness(content, ctx.ocr.fields).ok
    assert "llm" not in pipeline.models.loaded
    assert any(e.action == "stage.summary.done" for e in ctx.audit)


def test_stage_drops_injected_hallucination() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    pipeline.config.models["llm"]["primary"] = {
        "impl": "stub_llm", "device": "cpu", "inject_hallucination": True,
    }
    ctx = pipeline.run_stage("summary", _ctx_with_ocr("en"))
    content = SummarySchema.model_validate(ctx.summary.content)
    # The injected fake Cholesterol=999 must not survive the faithfulness gate.
    assert all(f.analyte != "Cholesterol" for f in content.lab_findings)
    assert check_faithfulness(content, ctx.ocr.fields).ok


# --- bake-off harness --------------------------------------------------------
def test_eval_set_loads_bilingual() -> None:
    items = load_eval_set()
    assert len(items) >= 12
    langs = {it.lang for it in items}
    assert {"en", "hi"} <= langs


def test_extraction_and_hindi_metrics() -> None:
    pred = SummarySchema(
        lab_findings=[LabFinding(analyte="Hemoglobin", value="9.5", unit="g/dL")],
    )
    gold = {"lab_findings": [{"analyte": "Hemoglobin", "value": "9.5"}]}
    assert extraction_prf(pred, gold)["f1"] == 1.0
    # Legacy metric: summaries are English-only now (patient-language surface
    # is produced at the voice boundary), so this always scores 0.
    assert hindi_quality(pred, gold) == 0.0


def test_bench_runner_produces_artifacts(tmp_path: Path) -> None:
    results = run_bench(models_filter=None, env_name="dev_4060", eval_path=None,
                        out_dir=tmp_path, force_stub=True)
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "REPORT.md").exists()
    assert len(results["models"]) == 4
    for mdl in results["models"]:
        assert 0.0 <= mdl["metrics"]["faithfulness"] <= 1.0
        assert "faithfulness" in mdl["metrics"]
    # On a box with no real runtime this is a stub/sample run.
    assert results["is_sample"] is True


@pytest.mark.parametrize(
    "ocr_name,summary_name",
    [
        # Free vs total: different units and non-overlapping intervals. These
        # bound clean at faithfulness 1.00 because normalize_analyte strips the
        # parenthetical gloss and both names reduce to the same stem.
        ("Thyroxine (FT4)", "Thyroxine (T4)"),
        ("Thyroxine (T4)", "Thyroxine (FT4)"),
        ("Triiodothyronine (FT3)", "Triiodothyronine (T3)"),
        ("Triiodothyronine (T3)", "Triiodothyronine"),
    ],
)
def test_abbreviated_fractions_never_bind(ocr_name, summary_name) -> None:
    fields = [OCRField(name=ocr_name, value="1.4", unit="ng/dL")]
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": summary_name, "value": "1.4", "unit": "ng/dL",
         "source_field": ocr_name}]})
    assert not check_faithfulness(s, fields).ok, \
        f"{summary_name!r} wrongly bound to {ocr_name!r}"


def test_free_t4_value_is_dropped_when_claimed_as_total_t4() -> None:
    """The misattribution must be removed from the stored summary, not just flagged."""
    fields = [OCRField(name="Thyroxine (FT4)", value="1.4", unit="ng/dL")]
    s = SummarySchema.model_validate({"lab_findings": [
        {"analyte": "Thyroxine (T4)", "value": "1.4", "unit": "ng/dL",
         "source_field": "Thyroxine (FT4)"}]})
    cleaned = drop_hallucinations(s, fields)
    assert cleaned.lab_findings == []
    assert "Thyroxine (T4)" in cleaned.unknowns


def test_stub_llm_handles_page_grouped_fields() -> None:
    """The no-deps fallback must survive the page-grouped prompt shape.

    fields_to_json emits {"page": i, "fields": [...]} wrappers as soon as ANY
    field carries page provenance -- which every real multi-page OCR session
    does. The stub parsed only the flat shape and died on f["value"], so the
    documented fallback crashed at stage [4] on exactly its intended input.
    """
    from core.env import EnvProfile
    from models.llm_stub import StubLLMAdapter
    from stages.summary_build import build_prompt, extract_fields_block

    paged = [
        OCRField(name="Hemoglobin", value="9.5", unit="g/dL", page_index=0),
        OCRField(name="Glucose", value="142", unit="mg/dL", page_index=1),
    ]
    system, user = build_prompt(paged, "hi")

    rows = extract_fields_block(user)
    assert rows, "page-grouped block flattened to nothing"
    assert all("value" in r for r in rows), f"wrapper leaked through: {rows}"

    adapter = StubLLMAdapter("llm", {}, EnvProfile.load("dev_4060"))
    out = adapter.generate(system, user, max_tokens=1024)   # must not raise
    assert "Hemoglobin" in out and "Glucose" in out, "fields from both pages missing"


def test_extract_fields_block_handles_both_shapes() -> None:
    from stages.summary_build import extract_fields_block, fields_to_json, FIELDS_OPEN, FIELDS_CLOSE

    for fields in ([OCRField(name="Hb", value="9.5")],
                   [OCRField(name="Hb", value="9.5", page_index=0)]):
        prompt = f"{FIELDS_OPEN}\n{fields_to_json(fields)}\n{FIELDS_CLOSE}"
        rows = extract_fields_block(prompt)
        assert rows == [{"name": "Hb", "value": "9.5"}], rows


def test_python_literal_with_possessive_apostrophe_is_diagnosed() -> None:
    """A single-quoted dict literal cannot survive a possessive apostrophe.

    "Dr. R Mehta's report" ends the string early; the trailing date then parses
    as bare tokens and ast raises a misleading "leading zeros" SyntaxError. This
    pins WHY llm_ollama requests constrained JSON -- the parser cannot be made
    to recover this, so the generator must not produce it.
    """
    from stages.summary_build import _parse_python_literal

    clean = "{'narrative_en': 'Dr A K Sharma issued a report on 21/04/2026.'}"
    possessive = "{'narrative_en': \"Dr. R Mehta's report on 21/04/2026.\"}"
    broken = "{'narrative_en': 'Dr. R Mehta's report on 21/04/2026.'}"

    assert _parse_python_literal(clean) is not None
    assert _parse_python_literal(possessive) is not None, "double-quoted form is valid"
    assert _parse_python_literal(broken) is None, "unescaped apostrophe must not parse"


def test_ollama_adapter_requests_constrained_json_by_default() -> None:
    """format=json is what keeps the model from emitting a Python dict literal."""
    from core.env import EnvProfile
    from models.llm_ollama import OllamaAdapter

    env = EnvProfile.load("dev_4060")
    assert OllamaAdapter("llm", {"model": "qwen2.5:3b-instruct"}, env).spec.get("json_mode", True)
    # explicit opt-out still honoured
    assert OllamaAdapter("llm", {"model": "x", "json_mode": False}, env).spec["json_mode"] is False
