"""Phase 5 acceptance tests (PLAN.md Phase 5 — Interpretation).

Covers the pure rule logic (range parsing, table + printed-range fallback,
low/normal/high/critical, unit-mismatch review) and the stage end-to-end: a
critical value surfaces as high-priority in the summary, output carries a STATUS
and no diagnosis, and the stage holds no model / loads no VRAM.
"""

from __future__ import annotations

from core.context import OCRField, OCRResult, SessionContext, SummaryDoc
from core.pipeline import Pipeline
import pytest

from stages.interpret_rules import (
    load_reference_table,
    normalize_analyte,
    parse_printed_range,
    interpret_value,
)

TABLE = load_reference_table()
#: The full LabQAR-derived table — normalization is exercised against this one
#: because the specimen-prefixed names only appear on real reports.
LABQAR = load_reference_table("data/labqar/reference_ranges_labqar.yaml")


# --- deterministic analyte-name normalization --------------------------------

@pytest.mark.parametrize(
    "printed,canonical",
    [
        ("Serum Sodium", "Sodium"),
        ("Serum Potassium", "Potassium"),
        ("Serum Chlorides", "Chloride"),          # prefix + plural
        ("Blood Urea", "Urea"),
        ("S.G.O.T", "Aspartate aminotransferase (AST, SGOT)"),   # dotted abbrev
        ("R.B.C. Count", "Red blood cell count"),
        ("Packed Cell Volume (PCV)", "Hematocrit"),              # abbrev gloss
    ],
)
def test_specimen_prefix_and_abbreviation_normalize(printed, canonical) -> None:
    hit = LABQAR.lookup(printed)
    assert hit is not None, f"{printed!r} did not resolve"
    assert hit["canonical"] == canonical


@pytest.mark.parametrize(
    "printed",
    [
        # Identity-changing tokens: these name DIFFERENT analytes with different
        # intervals. Normalizing them away would silently apply the wrong range
        # — the failure mode that ruled out fuzzy matching (see nlpplan.md).
        "Urine Sodium",
        "Urine Creatinine",
        "CREATININE,URINE",
        "24 hr Urine Protein",
        "Serum Free Testosterone",
    ],
)
def test_identity_tokens_refuse_normalization(printed) -> None:
    assert normalize_analyte(printed) == [], f"{printed!r} produced candidates"


def test_identity_guarded_name_does_not_leak_to_base_analyte() -> None:
    """'Urine Sodium' must not inherit the serum sodium interval."""
    serum = LABQAR.lookup("Serum Sodium")
    urine = LABQAR.lookup("Urine Sodium")
    assert serum is not None
    assert urine is None or urine["canonical"] != serum["canonical"]


@pytest.mark.parametrize(
    "a,b",
    [
        # Near-identical names, deliberately distinct entries.
        ("Direct Bilirubin", "Indirect Bilirubin"),
        ("Direct Bilirubin", "Bilirubin"),
        ("VLDL", "Total Cholesterol"),
        ("Transferrin Saturation", "Transferrin"),
        ("Ionic Calcium", "Calcium"),
        ("Blood Sugar (R)", "Glucose Fasting"),
    ],
)
def test_near_identical_analytes_stay_distinct(a, b) -> None:
    ha, hb = LABQAR.lookup(a), LABQAR.lookup(b)
    assert ha is not None and hb is not None, f"{a!r}/{b!r} — one is missing"
    assert ha["canonical"] != hb["canonical"], f"{a!r} collapsed into {b!r}"
    assert ha.get("default") != hb.get("default") or ha.get("unit") != hb.get("unit")


# --- pure range parsing ------------------------------------------------------
def test_parse_two_sided_and_one_sided_ranges() -> None:
    assert parse_printed_range("13.0-17.0") == (13.0, 17.0)
    assert parse_printed_range("0 - 150") == (0.0, 150.0)
    assert parse_printed_range("< 200") == (None, 200.0)
    assert parse_printed_range("> 30") == (30.0, None)
    assert parse_printed_range("") == (None, None)
    assert parse_printed_range(None) == (None, None)


# --- status classification ---------------------------------------------------
def test_low_normal_high_from_table() -> None:
    low = interpret_value("Hemoglobin", "9.5", "g/dL", "13.0-17.0", TABLE)
    assert low.status == "low"
    normal = interpret_value("Hemoglobin", "14.0", "g/dL", None, TABLE)
    assert normal.status == "normal"
    high = interpret_value("Total Cholesterol", "232", "mg/dL", None, TABLE)
    assert high.status == "high"


def test_critical_threshold() -> None:
    crit = interpret_value("Glucose Fasting", "420", "mg/dL", None, TABLE)
    assert crit.status == "critical"
    assert crit.high_priority is True


def test_direction_one_sided_not_flagged_high() -> None:
    # Vitamin D is low_only: a value above the interval is still not "high".
    v = interpret_value("Vitamin D", "120", "ng/mL", None, TABLE)
    assert v.status == "normal"
    low = interpret_value("Vitamin D", "18", "ng/mL", None, TABLE)
    assert low.status == "low"


def test_unit_mismatch_needs_review() -> None:
    r = interpret_value("Hemoglobin", "9.5", "mg/dL", None, TABLE)  # wrong unit
    assert r.status == "unknown"
    assert r.needs_review and "unit_mismatch" in (r.review_reason or "")


def test_printed_range_fallback_for_unknown_analyte() -> None:
    r = interpret_value("Mystery Marker", "5", None, "1-3", TABLE)
    assert r.status == "high"          # 5 > printed high 3
    r2 = interpret_value("Mystery Marker", "2", None, "1-3", TABLE)
    assert r2.status == "normal"


def test_unparseable_value_is_unknown() -> None:
    r = interpret_value("Hemoglobin", "n/a", "g/dL", "13.0-17.0", TABLE)
    assert r.status == "unknown" and r.needs_review


# --- stage end-to-end --------------------------------------------------------
def _ctx_with_summary() -> SessionContext:
    ctx = SessionContext(session_id="p5test", lang="hi")
    ctx.ocr = OCRResult(fields=[
        OCRField(name="Hemoglobin", value="9.5", unit="g/dL"),
        OCRField(name="Glucose Fasting", value="420", unit="mg/dL"),
    ])
    ctx.summary = SummaryDoc(version=1, content={
        "lab_findings": [
            {"analyte": "Hemoglobin", "value": "9.5", "unit": "g/dL", "ref_range": "13.0-17.0"},
            {"analyte": "Glucose Fasting", "value": "420", "unit": "mg/dL", "ref_range": "70-100"},
            {"analyte": "Creatinine", "value": "1.0", "unit": "mg/dL", "ref_range": "0.7-1.3"},
        ],
    })
    return ctx


def test_interpret_stage_flags_and_surfaces_high_priority() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    ctx = pipeline.run_stage("interpret", _ctx_with_summary())

    by = {f.analyte: f for f in ctx.interpretations}
    assert by["Hemoglobin"].status == "low"
    assert by["Glucose Fasting"].status == "critical"
    assert by["Glucose Fasting"].high_priority is True
    assert by["Creatinine"].status == "normal"

    # High-priority + abnormal surfaced into the summary for the doctor.
    hp = ctx.summary.content["high_priority_flags"]
    assert any(x["analyte"] == "Glucose Fasting" for x in hp)
    abn = {x["analyte"] for x in ctx.summary.content["abnormal_flags"]}
    assert {"Hemoglobin", "Glucose Fasting"} <= abn
    assert "Creatinine" not in abn  # normal is not surfaced as abnormal

    assert any(e.action == "stage.interpret.done" for e in ctx.audit)


def _contradiction_stage():
    from core.env import AppConfig
    from core.model_manager import ModelManager
    from stages.s5_interpret import InterpretStage

    cfg = AppConfig.load("dev_4060")
    return InterpretStage(cfg, ModelManager(cfg))


def _ctx_with_narrative(text: str) -> SessionContext:
    ctx = SessionContext(session_id="narr01")
    ctx.summary = SummaryDoc(content={"narrative_en": text})
    return ctx


def test_narrative_contradicting_the_flags_is_flagged() -> None:
    """The narrative is written BEFORE the rules run, and LLMs get numeric
    comparisons wrong — MedGemma called an above-range WBC and a below-range
    platelet count 'within the normal range'. Rules win; mismatches are reported.
    """
    from core.context import LabFlag

    stage = _contradiction_stage()
    flags = [LabFlag(analyte="WBC", value="11200", status="high"),
             LabFlag(analyte="Platelets", value="1.4", status="low")]
    ctx = _ctx_with_narrative(
        "The WBC count was 11200 /cumm, within the normal range of 4000-11000 /cumm. "
        "Platelet count was 1.4 lakhs/cumm, also within the normal range of 1.5-4.1."
    )
    found = stage._narrative_contradictions(ctx, flags)
    assert len(found) == 2                      # matched despite "Platelet count"
    assert ctx.summary.content["narrative_review"] == found


def test_correct_narrative_raises_no_contradiction() -> None:
    from core.context import LabFlag

    stage = _contradiction_stage()
    flags = [LabFlag(analyte="Hemoglobin", value="9.5", status="low"),
             LabFlag(analyte="WBC", value="11200", status="high")]
    # Decimal points must not truncate the clause before the verdict.
    ctx = _ctx_with_narrative(
        "Hemoglobin is 9.5 g/dL, below the reference range of 13.0-17.0 g/dL; "
        "WBC count is 11200 /cumm, above the reference range of 4000-11000 /cumm."
    )
    assert stage._narrative_contradictions(ctx, flags) == []


def test_analyte_key_merges_spelling_variants() -> None:
    """The union merge keys on the analyte name. Without spelling normalization a
    real 16-page session produced 65 flags for 59 values, because the model wrote
    "Haemoglobin" where OCR read "Hemoglobin" — duplicate rows to a clinician."""
    from stages.s5_interpret import InterpretStage as S

    assert S._analyte_key("Haemoglobin") == S._analyte_key("Hemoglobin")
    assert S._analyte_key("R A FACTOR") == S._analyte_key("RA Factor")
    assert S._analyte_key("Leucocyte Count") == S._analyte_key("Leukocyte Count")
    # ...but genuinely different analytes must NOT collapse together.
    assert S._analyte_key("T3") != S._analyte_key("T4")
    assert S._analyte_key("HDL") != S._analyte_key("LDL")
    assert S._analyte_key("Total Bilirubin") != S._analyte_key("Direct Bilirubin")


def test_chained_analytes_do_not_false_positive() -> None:
    """One sentence can chain analytes with opposite verdicts. Judging on the
    whole clause read the NEXT analyte's verdict as this one's and reported a
    contradiction that was not there."""
    from core.context import LabFlag

    stage = _contradiction_stage()
    flags = [LabFlag(analyte="Hemoglobin", value="9.5", status="low"),
             LabFlag(analyte="WBC", value="11200", status="high")]
    ctx = _ctx_with_narrative(
        "Hemoglobin at 9.5 g/dL, below the reference range of 13.0-17.0 g/dL "
        "and WBC count at 11200 /cumm, above the reference range of 4000-11000 /cumm."
    )
    assert stage._narrative_contradictions(ctx, flags) == []


def test_inverted_direction_is_flagged() -> None:
    from core.context import LabFlag

    stage = _contradiction_stage()
    flags = [LabFlag(analyte="Hemoglobin", value="9.5", status="low")]
    ctx = _ctx_with_narrative("Hemoglobin at 9.5 g/dL is above the range of 13.0-17.0 g/dL.")
    assert len(stage._narrative_contradictions(ctx, flags)) == 1


def test_interpret_holds_no_model_or_vram() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    pipeline.run_stage("interpret", _ctx_with_summary())
    assert pipeline.models.loaded == []


def test_no_diagnosis_in_output_schema() -> None:
    """Product invariant: interpretation emits a status, never a diagnosis."""
    pipeline = Pipeline(env_name="dev_4060")
    ctx = pipeline.run_stage("interpret", _ctx_with_summary())
    for flag in ctx.interpretations:
        keys = set(flag.model_dump().keys())
        # Only status/priority metadata — no free-text diagnosis/advice field.
        assert keys <= {"analyte", "value", "unit", "ref_range", "status", "high_priority"}
        assert flag.status in {"low", "normal", "high", "critical", "unknown"}


# --- a table row without bounds must never read as "normal" ------------------
# Regression: resolve_interval treated any table HIT as sufficient, so a row
# that existed but carried no range compared vacuously in both directions and
# every value came back "normal" — an HbA1c of 9.8 % included.

def test_rangeless_table_entry_is_unknown_not_normal() -> None:
    from stages.interpret_rules import ReferenceTable

    table = ReferenceTable(by_alias={"mystery": {"canonical": "Mystery", "unit": "mg/dL"}})
    result = interpret_value("Mystery", "99999", "mg/dL", None, table)
    assert result.status == "unknown", "bound-less row silently declared normal"
    assert result.needs_review
    assert result.review_reason == "no_reference_range"


def test_rangeless_table_entry_falls_back_to_printed_range() -> None:
    """A row we cannot compare must still use the report's own printed range."""
    from stages.interpret_rules import ReferenceTable

    table = ReferenceTable(by_alias={"mystery": {"canonical": "Mystery"}})
    result = interpret_value("Mystery", "250", None, "0-200", table)
    assert result.status == "high"


@pytest.mark.parametrize("table", [TABLE, LABQAR])
def test_no_shipped_analyte_reads_normal_without_a_range(table) -> None:
    """No BOUND-LESS row in a shipped table may decide a status.

    Scoped to rows that carry no bounds at all. A row with a single bound and a
    ``direction`` gate (Vitamin D, HDL, B12 — only the low side is clinically
    flagged) legitimately reads high values as normal; that is the gate working,
    not this defect.
    """
    from stages.interpret_rules import _entry_has_range

    offenders = [
        entry["canonical"]
        for entry in {id(e): e for e in table.by_alias.values()}.values()
        if entry.get("canonical") and not _entry_has_range(entry)
        and interpret_value(entry["canonical"], "99999", None, None, table).status != "unknown"
    ]
    assert offenders == [], f"bound-less row decided a status for: {offenders}"


def test_duplicate_alias_keeps_the_populated_entry() -> None:
    """A placeholder row must not displace one that carries a real interval.

    'Glycated hemoglobin' claimed the alias 'hba1c' and, under last-write-wins,
    silently replaced the real 4.0-5.6 % / high_only entry.
    """
    assert TABLE.lookup("HbA1c")["canonical"] == "HbA1c"
    assert interpret_value("HbA1c", "9.8", "%", None, TABLE).status == "high"


@pytest.mark.parametrize("table", [TABLE, LABQAR])
def test_alias_collisions_are_recorded_not_silent(table) -> None:
    """Curation errors stay reviewable: every collision is reported."""
    for alias, loser, winner in table.collisions:
        assert alias and winner, "collision recorded without a winner"
        assert loser != winner


# --- identity guard: word boundaries, and abbreviation-encoded fractions ------

@pytest.mark.parametrize(
    "printed,canonical",
    [
        # Substring matching refused these outright: 'Copper' tripped "pp",
        # 'Taurine' tripped "urine", 'hCG' tripped "ionic".
        ("Serum Copper", "Copper"),
        ("Serum Taurine", "Taurine"),
        ("Human chorionic gonadotropin", "Human chorionic gonadotropin (hCG)"),
    ],
)
def test_word_boundary_guard_stops_refusing_valid_analytes(printed, canonical) -> None:
    hit = LABQAR.lookup(printed)
    assert hit is not None, f"{printed!r} still refused"
    assert hit["canonical"] == canonical


@pytest.mark.parametrize(
    "printed",
    ["Indirect Bilirubin", "unconjugated bilirubin", "VLDL Cholesterol", "vldl",
     "Blood Sugar PP", "Ionic Calcium", "HDL Cholesterol", "Thyroxine (FT4)",
     "Triiodothyronine (FT3)"],
)
def test_word_boundary_guard_still_refuses_distinct_analytes(printed) -> None:
    """Every name that must stay guarded carries its own explicit token."""
    assert normalize_analyte(printed) == [], f"{printed!r} leaked past the guard"


@pytest.mark.parametrize(
    "a,b",
    [
        # Free vs total: the discriminator is in the ABBREVIATION, not a "free"
        # token, and stripping the parenthetical gloss collapsed both to
        # "thyroxine" / "triiodothyronine".
        ("Thyroxine (FT4)", "Thyroxine (T4)"),
        ("Triiodothyronine (FT3)", "Triiodothyronine (T3)"),
        ("Triiodothyronine (T3)", "Triiodothyronine"),
    ],
)
def test_abbreviated_fractions_stay_distinct(a, b) -> None:
    ha, hb = LABQAR.lookup(a), LABQAR.lookup(b)
    assert ha is not None and hb is not None, f"{a!r}/{b!r} — one is missing"
    assert ha["canonical"] != hb["canonical"], f"{a!r} collapsed into {b!r}"
