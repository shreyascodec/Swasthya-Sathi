"""Phase 6 acceptance tests (PLAN.md Phase 6 — Intake Q&A).

Covers deterministic trigger firing (a stale report fires the gap question and
references the real date), grounded condition follow-ups, the missing-companion
trigger, top-N selection, the off-bank guardrail (a question can only come from
the bank), bilingual deterministic rendering with no stray slots, the stage
end-to-end (no model needed to build questions), and STT answer capture attaching
a transcript to the summary via the stub recognizer.
"""

from __future__ import annotations

from datetime import date

from core.context import (IntakeQuestion, LabFlag, OCRResult, SessionContext,
                          SummaryDoc)
from core.pipeline import Pipeline
from stages.intake_qa_rules import (
    IntakeFacts,
    LabFact,
    load_question_bank,
    select,
    validate_from_bank,
)

BANK = load_question_bank()


def _facts(labs=None, present=None, dates=None, meds=None, today=None) -> IntakeFacts:
    return IntakeFacts(
        labs=labs or [],
        present_analytes=present or set(),
        report_dates=dates or [],
        medications=meds or [],
        today=today or date(2026, 7, 17),
    )


# --- bank + guardrail --------------------------------------------------------
def test_bank_loads_enough_patterns() -> None:
    assert len(BANK) >= 15
    cats = {p.category for p in BANK}
    assert {"gap", "missing_report", "condition_follow_up", "standard_history"} <= cats


def test_off_bank_guardrail() -> None:
    assert validate_from_bank("cond_anemia", BANK) is True
    assert validate_from_bank("totally_made_up_question", BANK) is False


# --- triggers ----------------------------------------------------------------
def test_stale_report_fires_and_references_real_date() -> None:
    facts = _facts(dates=["12/05/2024"])   # ~26 months before 2026-07-17
    qs = select(BANK, facts, max_questions=5, stale_report_months=6)
    gap = [q for q in qs if q.pattern_id == "gap_stale_report"]
    assert gap, "stale report should fire the gap question"
    assert "12/05/2024" in gap[0].text_en
    assert "12/05/2024" in gap[0].text_hi


def test_recent_report_does_not_fire_gap() -> None:
    facts = _facts(dates=["12/05/2026"])   # 2 months old -> not stale
    qs = select(BANK, facts, stale_report_months=6)
    assert not any(q.pattern_id == "gap_stale_report" for q in qs)


def test_condition_followup_grounded_in_value() -> None:
    facts = _facts(labs=[LabFact("Glucose Fasting", "142", "mg/dL", "high")],
                   present={"glucose fasting"})
    qs = select(BANK, facts)
    hg = [q for q in qs if q.pattern_id == "cond_high_glucose"]
    assert hg and "142" in hg[0].text_en
    assert "Glucose Fasting" in hg[0].text_en


def test_missing_companion_test_fires_then_suppressed() -> None:
    labs = [LabFact("Glucose Fasting", "142", "mg/dL", "high")]
    fires = select(BANK, _facts(labs=labs, present={"glucose fasting"}))
    assert any(q.pattern_id == "missing_hba1c" for q in fires)
    # If HbA1c is already present, the missing-test trigger must NOT fire.
    suppressed = select(BANK, _facts(labs=labs, present={"glucose fasting", "hba1c"}))
    assert not any(q.pattern_id == "missing_hba1c" for q in suppressed)


def test_top_n_selection_prioritises_grounded() -> None:
    facts = _facts(labs=[LabFact("Creatinine", "1.6", "mg/dL", "high")],
                   present={"creatinine"})
    qs = select(BANK, facts, max_questions=3)
    assert len(qs) == 3
    # Highest priority first, and the grounded renal question outranks generic history.
    assert qs[0].priority >= qs[-1].priority
    assert qs[0].pattern_id == "cond_renal"


def test_render_has_no_unfilled_slots() -> None:
    facts = _facts(labs=[LabFact("Hemoglobin", "9.5", "g/dL", "low")],
                   present={"hemoglobin"}, dates=["01/01/2020"], meds=["Tab Metformin 500mg"])
    for q in select(BANK, facts, max_questions=5):
        assert "{" not in q.text_en and "}" not in q.text_en
        assert "{" not in q.text_hi and "}" not in q.text_hi


# --- stage end-to-end --------------------------------------------------------
def _ctx() -> SessionContext:
    ctx = SessionContext(session_id="p6test", lang="hi")
    ctx.ocr = OCRResult(fields=[])
    ctx.summary = SummaryDoc(version=1, content={
        "lab_findings": [{"analyte": "Glucose Fasting", "value": "142", "unit": "mg/dL"}],
        "report_dates": ["01/01/2020"],
        "medications": [{"name": "Tab Metformin 500mg"}],
    })
    ctx.interpretations = [
        LabFlag(analyte="Glucose Fasting", value="142", unit="mg/dL", status="high"),
    ]
    return ctx


def test_stage_builds_questions_in_language_no_model() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    ctx = pipeline.run_stage("intake_qa", _ctx())

    assert ctx.questions, "questions should be generated"
    assert all(isinstance(q, IntakeQuestion) for q in ctx.questions)
    # Rendered in Hindi (patient language) and every question is from the bank.
    assert all(validate_from_bank(q.pattern_id, BANK) for q in ctx.questions)
    assert any(q.pattern_id == "cond_high_glucose" for q in ctx.questions)
    assert any(q.pattern_id == "gap_stale_report" for q in ctx.questions)
    # Building questions needs no model/VRAM.
    assert pipeline.models.loaded == []
    assert any(e.action == "stage.intake_qa.done" for e in ctx.audit)


def test_stt_answer_capture_attaches_transcript(tmp_path) -> None:
    pipeline = Pipeline(env_name="dev_4060")
    pipeline.config.models["stt"]["primary"] = {"impl": "stub_stt", "device": "cpu"}
    stage = pipeline.stage_by_name("intake_qa")

    ctx = pipeline.run_stage("intake_qa", _ctx())
    qid = ctx.questions[0].id

    audio = tmp_path / "answer.wav"
    audio.write_bytes(b"")                       # placeholder clip
    (tmp_path / "answer.wav.txt").write_text("हाँ, मैं मेटफॉर्मिन लेता हूँ।", encoding="utf-8")

    answer = stage.capture_answer(ctx, qid, str(audio))
    assert answer.transcript == "हाँ, मैं मेटफॉर्मिन लेता हूँ।"
    assert ctx.answers and ctx.answers[0].question_id == qid
    attached = ctx.summary.content["intake_answers"]
    assert attached[0]["transcript"] == "हाँ, मैं मेटफॉर्मिन लेता हूँ।"
    assert pipeline.models.loaded == []          # STT released after capture


def test_capture_answer_replaces_on_rerecord(tmp_path) -> None:
    """Re-answering the same question must REPLACE, not append.

    A patient who mis-speaks re-records; two takes attached to one question
    leaves the doctor with contradictory answers and no way to tell which is
    current.
    """
    pipeline = Pipeline(env_name="dev_4060")
    pipeline.config.models["stt"]["primary"] = {"impl": "stub_stt", "device": "cpu"}
    stage = pipeline.stage_by_name("intake_qa")

    ctx = pipeline.run_stage("intake_qa", _ctx())
    qid = ctx.questions[0].id

    audio = tmp_path / "answer.wav"
    audio.write_bytes(b"")
    (tmp_path / "answer.wav.txt").write_text("पहला जवाब", encoding="utf-8")
    stage.capture_answer(ctx, qid, str(audio))

    # Patient re-records the same question.
    (tmp_path / "answer.wav.txt").write_text("सही जवाब", encoding="utf-8")
    stage.capture_answer(ctx, qid, str(audio))

    same_q = [a for a in ctx.answers if a.question_id == qid]
    assert len(same_q) == 1, f"re-record duplicated the answer: {ctx.answers}"
    assert same_q[0].transcript == "सही जवाब", "kept the stale take"

    attached = [a for a in ctx.summary.content["intake_answers"]
                if a["question_id"] == qid]
    assert len(attached) == 1, f"re-record duplicated in summary: {attached}"
    assert attached[0]["transcript"] == "सही जवाब"
