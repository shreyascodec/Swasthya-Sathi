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
        "action": "Refer urgently to a First Referral Unit (FRU)/CHC. Call 108 if any danger sign is present.",
    },
    "moderate": {
        "label": "Needs attention",
        "action": "Refer to the Medical Officer and schedule a follow-up ANC visit soon; monitor the flagged values.",
    },
    "low": {
        "label": "Low risk",
        "action": "Continue routine ANC. Attend the next scheduled visit and keep taking IFA/calcium as advised.",
    },
    "unknown": {
        "label": "Assessment incomplete",
        "action": "Not enough readable values to assess risk. Re-check the report/vitals with the health worker.",
    },
}


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
    seen: set[str] = set()

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
            add_param("Blood Pressure", value, unit or "mmHg", st)
        elif _is_urine_protein(name):
            add_param("Urine Protein", value or "-", unit, _urine_protein_status(str(value)))

    # 2) Everything else from the deterministic interpretations (Hb, sugar,
    #    pulse, temp, platelets, and separate systolic/diastolic if present).
    for it in interpretations:
        name = it.analyte if hasattr(it, "analyte") else it.get("analyte", "")
        value = it.value if hasattr(it, "value") else it.get("value", "")
        unit = it.unit if hasattr(it, "unit") else it.get("unit")
        status = it.status if hasattr(it, "status") else it.get("status", "unknown")
        if _is_bp(name):  # a combined BP already handled above
            continue
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

    # 4) Tier. Red flags (critical value or reported danger sign) force HIGH.
    statuses = [p["status"] for p in params]
    if red_flags or "critical" in statuses:
        tier = "high"
    elif any(s in ("high", "low") for s in statuses):
        tier = "moderate"
    elif params and all(s == "normal" for s in statuses):
        tier = "low"
    else:
        tier = "unknown"

    meta = _TIER_META[tier]
    return {
        "tier": tier,
        "tier_label": meta["label"],
        "action": meta["action"],
        "reasons": reasons,
        "red_flags": red_flags,
        "parameters": params,
        "danger_signs": danger_signs,
        "gestational_age": gestational_age,
        "reviewed": False,
        "source": "mch-maternal-poc-1",
    }
