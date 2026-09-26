"""Maternal (antenatal) risk stratification — Swasthya Sakhi MCH mode.

Pure, deterministic, NO model. Sits on top of the per-parameter statuses the
interpret stage already computed (against data/mch/maternal_thresholds.yaml) and
folds in two things the numeric engine can't: a combined blood-pressure reading
("150/100"), a urine-protein grade ("++"), and the patient's spoken answers to
antenatal DANGER-SIGN questions.

Output is a RISK TIER (low | moderate | high) + reasons + a recommended action —
it is triage/referral guidance, never a diagnosis. Mandatory red-flag overrides
(severe BP, severe anaemia, any critical value, any reported danger sign) force
HIGH regardless of everything else and can never be suppressed.

⚠️ Tiering rules and the referral wording are POC placeholders PENDING CLINICIAN
REVIEW (see data/mch/maternal_thresholds.yaml).
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _key(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _is_bp(name: str) -> bool:
    k = _key(name)
    return k in ("bp", "bloodpressure") or "bloodpressure" in k or k == "bpmmhg"


def _is_urine_protein(name: str) -> bool:
    k = _key(name)
    return ("protein" in k or "albumin" in k) and ("urine" in k or "urinary" in k or k in ("protein", "albumin", "urineprotein", "urinealbumin"))


# --- blood pressure ----------------------------------------------------------
def _bp_status(value: str) -> tuple[str, int | None, int | None]:
    """Parse 'sys/dia' and grade against ACOG/WHO cutoffs. Returns (status, sys, dia)."""
    nums = _NUM.findall(value or "")
    if len(nums) < 2:
        return ("unknown", None, None)
    sys, dia = int(float(nums[0])), int(float(nums[1]))
    if sys >= 160 or dia >= 110:
        return ("critical", sys, dia)
    if sys >= 140 or dia >= 90:
        return ("high", sys, dia)
    return ("normal", sys, dia)


# --- urine protein -----------------------------------------------------------
def _urine_protein_status(value: str) -> str:
    v = str(value or "").strip().lower()
    if not v:
        return "unknown"
    if any(t in v for t in ("nil", "absent", "negative", "none")):
        return "normal"
    plus = v.count("+")
    if plus >= 3 or "3+" in v or "+++" in v:
        return "critical"
    if plus >= 1 or "trace" in v or "present" in v or "positive" in v:
        return "high"
    return "unknown"


# --- danger-sign answers -----------------------------------------------------
_AFFIRM = ("yes", "yeah", "yep", "haan", "haa", "ha", "हाँ", "हां", "हा")
_NEGATE = ("no", "nope", "nahi", "nahin", "नहीं", "नही")


def _is_affirmative(transcript: str) -> bool | None:
    t = str(transcript or "").strip().lower()
    if not t:
        return None
    if any(re.search(rf"(^|\W){re.escape(n)}(\W|$)", t) for n in _NEGATE):
        return False
    if any(re.search(rf"(^|\W){re.escape(a)}(\W|$)", t) for a in _AFFIRM):
        return True
    return None


_TIER_META = {
    "high": {
        "label": "High risk",
        # Worker/doctor copy (PMSMA). Never spoken to the woman as a "high risk" label.
        "action": "Immediate referral to a higher facility. Review with ANM/Doctor and follow maternal health protocols.",
        "patient_message": "Some findings require further medical review. Please visit the recommended health facility.",
    },
    "moderate": {
        "label": "Needs attention",
        "action": "Please review with ANM/Doctor and schedule a follow-up ANC visit soon; monitor the flagged values.",
        "patient_message": "Some findings require further medical review. Please visit the recommended health facility.",
    },
    "low": {
        "label": "Low risk",
        "action": "No high-risk pregnancy factors identified. Continue routine ANC follow-up. Next visit: 4 weeks.",
        "patient_message": "Please continue your routine check-ups as advised by the health worker.",
    },
    "unknown": {
        "label": "Assessment incomplete",
        "action": "Capture LMP/gestational age, blood pressure, and hemoglobin before completing referral.",
        "patient_message": "The health worker will finish a few measurements, then tell you the next step.",
    },
}

# Prototype Q&A: assessment should not be treated as complete without these.
_MANDATORY = ("hemoglobin", "bloodpressure", "gestationalage")


def _hb_grams(value: str) -> float | None:
    nums = _NUM.findall(value or "")
    if not nums:
        return None
    n = float(nums[0])
    # Some Indian reports print Hb in g/L (e.g. 64); leave as-is if already g/dL-like.
    return n


def _is_hb(name: str) -> bool:
    k = _key(name)
    return k in ("hemoglobin", "haemoglobin", "hb", "hgb") or k.startswith("hemoglobin")


def _is_ferritin(name: str) -> bool:
    return "ferritin" in _key(name)


def _is_age(name: str) -> bool:
    k = _key(name)
    return k in ("age", "maternalage", "ageyears")


def assess_maternal_risk(findings, interpretations, *, questions=None, answers=None,
                         gestational_age=None) -> dict:
    """Compute the maternal risk assessment. Pure; inputs are plain dicts/objects."""
    findings = findings or []
    interpretations = interpretations or []
    questions = questions or []
    answers = answers or []

    params: list[dict] = []
    reasons: list[str] = []
    red_flags: list[str] = []
    pmsma_rules: list[dict] = []
    seen: set[str] = set()
    hb_g: float | None = None
    bp_st: str | None = None
    protein_st: str | None = None
    age_y: float | None = None

    def add_param(name, value, unit, status):
        key = _key(name)
        if key in seen:
            return
        seen.add(key)
        disp = f"{value}{(' ' + unit) if unit else ''}".strip()
        params.append({"name": name, "value": disp, "status": status})
        if status == "critical":
            red_flags.append(f"{name} {disp} is critically abnormal")
            reasons.append(f"{name} {disp} — critical")
        elif status in ("high", "low"):
            reasons.append(f"{name} {disp} is {status}")

    # 1) Blood pressure + urine protein from the raw findings (numeric engine
    #    can't read a combined "150/100" or a "++" grade).
    for f in findings:
        name = f.get("analyte", "") if isinstance(f, dict) else getattr(f, "analyte", "")
        value = f.get("value", "") if isinstance(f, dict) else getattr(f, "value", "")
        unit = f.get("unit") if isinstance(f, dict) else getattr(f, "unit", None)
        if _is_bp(name) and "/" in str(value):
            st, _sys, _dia = _bp_status(str(value))
            bp_st = st
            add_param("Blood Pressure", value, unit or "mmHg", st)
        elif _is_urine_protein(name):
            protein_st = _urine_protein_status(str(value))
            add_param("Urine Protein", value or "-", unit, protein_st)

    # 2) Everything else from the deterministic interpretations (Hb, sugar,
    #    pulse, temp, platelets, and separate systolic/diastolic if present).
    for it in interpretations:
        name = it.analyte if hasattr(it, "analyte") else it.get("analyte", "")
        value = it.value if hasattr(it, "value") else it.get("value", "")
        unit = it.unit if hasattr(it, "unit") else it.get("unit")
        status = it.status if hasattr(it, "status") else it.get("status", "unknown")
        if _is_bp(name):  # a combined BP already handled above
            continue
        if _is_hb(name):
            hb_g = _hb_grams(str(value))
        if _is_age(name):
            age_y = _hb_grams(str(value))
        k = _key(name)
        if "systolic" in k or "diastolic" in k:
            if status == "critical":
                bp_st = "critical"
            elif status == "high" and bp_st != "critical":
                bp_st = "high"
            elif bp_st is None:
                bp_st = status if status in ("normal", "high", "critical") else bp_st
        add_param(name, value, unit, status)

    # 3) Danger-sign answers — a reported danger sign is a red flag.
    q_by_id = {q.id: q for q in questions} if questions else {}
    danger_signs: list[dict] = []
    for a in answers:
        qid = a.question_id if hasattr(a, "question_id") else a.get("question_id")
        transcript = a.transcript if hasattr(a, "transcript") else a.get("transcript", "")
        q = q_by_id.get(qid)
        pattern = getattr(q, "pattern_id", "") if q else ""
        qtext = getattr(q, "rendered_text", "") if q else ""
        if not pattern.startswith("danger_"):
            continue
        aff = _is_affirmative(transcript)
        danger_signs.append({"question": qtext, "answer": transcript, "flag": aff is True})
        if aff is True:
            red_flags.append(f"Reported danger sign: {qtext}")
            reasons.append(f"Patient reported: {qtext}")

    # 4) PMSMA rule library (prototype requirement). Labels are for the ANM/doctor
    #    card only — they are never a diagnosis.
    def fire(rule_id: str, condition: str, evidence: str, *, red: bool = False):
        pmsma_rules.append({"id": rule_id, "condition": condition, "evidence": evidence})
        reasons.append(f"{condition} ({rule_id}): {evidence}")
        if red:
            red_flags.append(f"{condition}: {evidence}")

    if hb_g is not None:
        if hb_g < 7:
            fire("R001", "Severe Anemia", f"Hb {hb_g:g} g/dL", red=True)
        elif hb_g < 10:
            fire("R002", "Moderate Anemia", f"Hb {hb_g:g} g/dL")
        elif hb_g < 11:
            reasons.append(f"Pregnancy anaemia (WHO): Hb {hb_g:g} g/dL")

    if bp_st == "critical":
        fire("R004", "Severe Hypertension", "BP ≥160/110", red=True)
    elif bp_st == "high":
        fire("R003", "Gestational Hypertension", "BP ≥140/90")

    if bp_st in ("high", "critical") and protein_st in ("high", "critical"):
        fire("R005", "Pre-eclampsia", "BP ≥140/90 with proteinuria", red=True)

    if age_y is not None:
        if age_y > 35:
            fire("R006", "Advanced Maternal Age", f"Age {age_y:g} years")
        elif age_y < 18:
            fire("R007", "Adolescent Pregnancy", f"Age {age_y:g} years")

    for p in params:
        if _is_ferritin(p["name"]) and p["status"] in ("low", "critical"):
            fire("R009", "Iron Deficiency", p["value"])

    # 5) Tier. Red flags (critical value, PMSMA high rule, or danger sign) → HIGH.
    statuses = [p["status"] for p in params]
    high_ids = {r["id"] for r in pmsma_rules if r["id"] in ("R001", "R004", "R005")}
    if red_flags or "critical" in statuses or high_ids:
        tier = "high"
    elif pmsma_rules or any(s in ("high", "low") for s in statuses):
        tier = "moderate"
    elif params and all(s == "normal" for s in statuses):
        tier = "low"
    else:
        tier = "unknown"

    present_keys = {_key(p["name"]) for p in params}
    if gestational_age:
        present_keys.add("gestationalage")
    mandatory_missing: list[str] = []
    if not any(_is_hb(p["name"]) for p in params):
        mandatory_missing.append("hemoglobin")
    if not any(_is_bp(p["name"]) for p in params) and "bloodpressure" not in present_keys:
        # Separate systolic+diastolic from interpret still count as BP.
        if not any("systolic" in _key(p["name"]) or "diastolic" in _key(p["name"]) for p in params):
            mandatory_missing.append("blood_pressure")
    if not gestational_age:
        mandatory_missing.append("gestational_age")

    # Q&A: do not treat the assessment as complete without Hb + BP. GA is
    # listed as missing but does not block OCR-only kiosk visits.
    blocking = [m for m in mandatory_missing if m in ("hemoglobin", "blood_pressure")]
    assessment_complete = not blocking
    if blocking and tier != "high":
        # Keep any HIGH (danger sign / severe anemia) even if a vital is missing.
        if not params and not red_flags:
            tier = "unknown"

    confirm_fields = [
        p["name"] for p in params
        if _is_hb(p["name"]) or _is_bp(p["name"])
        or "sugar" in _key(p["name"]) or "glucose" in _key(p["name"])
    ]
    if gestational_age:
        confirm_fields.append("Gestational Age")

    meta = _TIER_META[tier]
    return {
        "tier": tier,
        "tier_label": meta["label"],
        "action": meta["action"],
        "patient_message": meta["patient_message"],
        "worker_action": meta["action"],
        "reasons": reasons,
        "red_flags": red_flags,
        "parameters": params,
        "danger_signs": danger_signs,
        "pmsma_rules": pmsma_rules,
        "mandatory_missing": mandatory_missing,
        "assessment_complete": assessment_complete,
        "confirm_fields": confirm_fields,
        "gestational_age": gestational_age,
        "reviewed": False,
        "source": "mch-maternal-poc-1",
        "guideline": "MoHFW PMSMA High-Risk Pregnancy (prototype placeholders)",
    }
