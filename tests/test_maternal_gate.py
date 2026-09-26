"""Maternal-appropriateness gate: an antenatal kiosk must not run a MALE patient's
report through the pregnancy pipeline.

Conservative by design — rejects only on a positive male signal with no female /
pregnancy marker, so a genuine ANC report (even one that never states sex) is
never blocked.
"""

from __future__ import annotations

from core.context import OCRResult, SessionContext
import server.main as m


def _ctx(raw_text: str) -> SessionContext:
    c = SessionContext(session_id="gate", lang="en")
    c.ocr = OCRResult(raw_text=raw_text)
    return c


def test_male_report_is_rejected():
    assert m._maternal_mismatch(_ctx("Ramesh Kumar  Age / Sex 52 Years / Male  Glucose 156"))
    assert m._maternal_mismatch(_ctx("Abdul Rahman 61 Years / Male  Creatinine 2.1"))
    assert m._maternal_mismatch(_ctx("Name: A. Kumar  52 Y / M  Hemoglobin 13.2"))


def test_female_or_antenatal_report_is_allowed():
    assert not m._maternal_mismatch(_ctx("Fatima Bano 31 Y / Female  Hemoglobin 9.6"))
    assert not m._maternal_mismatch(_ctx("Kavita Kumari 22 Y / F  34 wk POG  BP 158/104"))
    assert not m._maternal_mismatch(_ctx("Priya Devi 24 Y / F  Hemoglobin 11.8"))


def test_ambiguous_report_fails_open():
    # No sex stated at all — must NOT block a legitimate ANC visit.
    assert not m._maternal_mismatch(_ctx("Hemoglobin 10.2 g/dL  Platelets 2.1"))
    assert not m._maternal_mismatch(_ctx(""))


def test_pregnancy_marker_overrides_stray_male_token():
    # "Male" appears (e.g. a male referring doctor) but pregnancy markers are present.
    assert not m._maternal_mismatch(_ctx("G2P1  LMP 12/02/2026  Hemoglobin 9.0  Ref: Dr X (Male)"))


def test_female_word_not_read_as_male():
    # \bmale\b must not match inside "Female".
    assert not m._maternal_mismatch(_ctx("Sex: Female  Hemoglobin 11.2"))
