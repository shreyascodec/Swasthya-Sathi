"""PMSMA prototype rules for maternal risk (Q&A + PRD)."""

from stages.maternal_risk import assess_maternal_risk


def _flag(analyte, value, unit, status):
    return {"analyte": analyte, "value": value, "unit": unit, "status": status}


def test_sita_devi_normal_pregnancy():
    findings = [{"analyte": "Blood Pressure", "value": "112/72", "unit": "mmHg"}]
    interps = [
        _flag("Hemoglobin", "11.8", "g/dL", "normal"),
        _flag("Ferritin", "42", "ng/mL", "normal"),
        _flag("HbA1c", "5.2", "%", "normal"),
        _flag("TSH", "2.1", "mIU/L", "normal"),
        _flag("Blood Sugar", "102", "mg/dL", "normal"),
    ]
    out = assess_maternal_risk(findings, interps, gestational_age="22 weeks")
    assert out["tier"] == "low"
    assert out["pmsma_rules"] == []
    assert "High risk" not in out["patient_message"]
    assert "routine" in out["patient_message"].lower() or "check-up" in out["patient_message"].lower()
    assert out["assessment_complete"] is True


def test_kamla_bai_severe_anemia_r001():
    findings = [{"analyte": "Blood Pressure", "value": "104/68", "unit": "mmHg"}]
    interps = [
        _flag("Hemoglobin", "6.4", "g/dL", "critical"),
        _flag("Ferritin", "8", "ng/mL", "critical"),
    ]
    out = assess_maternal_risk(findings, interps, gestational_age="28 weeks")
    assert out["tier"] == "high"
    ids = {r["id"] for r in out["pmsma_rules"]}
    assert "R001" in ids
    assert "R009" in ids
    assert "High risk" not in out["patient_message"]
    assert "medical review" in out["patient_message"].lower()
    assert any("Immediate referral" in out["action"] or "ANM" in out["action"] for _ in [0])


def test_moderate_anemia_r002_not_high():
    findings = [{"analyte": "Blood Pressure", "value": "118/76", "unit": "mmHg"}]
    interps = [_flag("Hemoglobin", "8.4", "g/dL", "low")]
    out = assess_maternal_risk(findings, interps)
    assert out["tier"] == "moderate"
    assert any(r["id"] == "R002" for r in out["pmsma_rules"])
    assert out["tier"] != "high"


def test_preeclampsia_r005():
    findings = [
        {"analyte": "Blood Pressure", "value": "150/100", "unit": "mmHg"},
        {"analyte": "Urine Protein", "value": "++", "unit": None},
    ]
    out = assess_maternal_risk(findings, [])
    ids = {r["id"] for r in out["pmsma_rules"]}
    assert "R003" in ids or "R004" in ids
    assert "R005" in ids
    assert out["tier"] == "high"


def test_missing_hb_is_incomplete_unless_high():
    findings = [{"analyte": "Blood Pressure", "value": "112/72", "unit": "mmHg"}]
    out = assess_maternal_risk(findings, [])
    assert "hemoglobin" in out["mandatory_missing"]
    assert out["assessment_complete"] is False
