"""Maternal intake-question differentiation.

Regression for the bug where every ANC report produced the SAME questions: the
five always-asked danger-sign patterns (priority 90-95) out-ranked and crowded
out the report-specific grounded follow-ups (anaemia 85, sugar 84), so with a
small budget only the identical danger screen (+ maybe one grounded) survived.

The fix reserves the danger-sign screen as a mandatory bucket that does NOT
consume the grounded budget, and adds grounded patterns for high BP / proteinuria
/ low platelets. These tests assert three ANC profiles now ask distinct
report-specific questions, on top of the shared danger screen.
"""

from __future__ import annotations

from pathlib import Path

from stages.intake_qa_rules import IntakeFacts, LabFact, load_question_bank, select

BANK = load_question_bank(
    Path(__file__).resolve().parent.parent / "data" / "question_bank" / "maternal_patterns.yaml"
)


def _facts(rows):  # rows: (analyte, value, unit, status)
    return IntakeFacts(
        labs=[LabFact(a, v, u, s) for a, v, u, s in rows],
        present_analytes={a.lower() for a, _, _, _ in rows},
    )


def _pick(rows):
    sel = select(BANK, _facts(rows), max_questions=6, max_grounded=3)
    danger = [q.pattern_id for q in sel if q.category == "danger_sign"]
    grounded = [q.pattern_id for q in sel if q.category != "danger_sign"]
    return danger, grounded


LOW = [
    ("Hemoglobin", "11.8", "g/dL", "normal"),
    ("Fasting Blood Sugar", "82", "mg/dL", "normal"),
    ("Platelets", "2.7", "lakhs/cumm", "normal"),
    ("Blood Pressure", "116/74", "mmHg", "normal"),
    ("Urine Protein", "Nil", "", "normal"),
]
MODERATE = [
    ("Hemoglobin", "9.6", "g/dL", "low"),
    ("Fasting Blood Sugar", "99", "mg/dL", "high"),
    ("Blood Sugar", "154", "mg/dL", "high"),
    ("Blood Pressure", "126/80", "mmHg", "normal"),
    ("Urine Protein", "Nil", "", "normal"),
]
HIGH = [
    ("Hemoglobin", "10.4", "g/dL", "low"),
    ("Platelets", "1.4", "lakhs/cumm", "low"),
    ("Blood Pressure", "158/104", "mmHg", "high"),
    ("Urine Protein", "++", "", "high"),
]


def test_danger_screen_always_asked_in_full():
    for rows in (LOW, MODERATE, HIGH):
        danger, _ = _pick(rows)
        assert danger == [
            "danger_headache_vision", "danger_bleeding", "danger_fetal_movement",
            "danger_swelling", "danger_fever",
        ]


def test_grounded_questions_differ_per_report():
    _, low = _pick(LOW)
    _, mod = _pick(MODERATE)
    _, high = _pick(HIGH)
    # The whole point: report-specific follow-ups are NOT identical across reports.
    assert low != mod
    assert mod != high
    assert low != high


def test_low_report_has_no_condition_followups():
    _, grounded = _pick(LOW)
    assert grounded == ["std_chief_complaint"]  # only the generic "anything else?"


def test_moderate_report_asks_anaemia_and_sugar():
    _, grounded = _pick(MODERATE)
    assert "cond_anemia" in grounded
    assert "cond_high_sugar" in grounded


def test_high_report_asks_bp_proteinuria_platelets():
    _, grounded = _pick(HIGH)
    assert "cond_high_bp" in grounded
    assert "cond_proteinuria" in grounded
    assert "cond_low_platelets" in grounded


def test_danger_signs_do_not_crowd_out_grounded():
    # With 5 danger signs and only 6 legacy slots, the OLD logic dropped all but
    # one grounded follow-up. Now a flagged report must surface its follow-ups.
    _, grounded = _pick(MODERATE)
    assert len(grounded) >= 2
