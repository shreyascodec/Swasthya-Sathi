"""Deterministic intake-question selection for Stage [6] — pure, no model.

Evaluates each question-bank pattern's structured trigger against the extracted
data (interpreted lab flags, report dates, medications), fills slots from data
only, and returns the top-N questions by priority. The model is NOT required to
produce question text — templates are pre-translated — so a question can only
ever come from the bank (the off-bank guardrail is structural).

``validate_from_bank`` is the explicit guardrail check used by the stage/tests:
a rendered question must carry a pattern_id that exists in the loaded bank.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

DEFAULT_BANK = Path(__file__).resolve().parent.parent / "data" / "question_bank" / "patterns.yaml"

_DATE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")


@dataclass
class Pattern:
    id: str
    category: str
    priority: int
    trigger: dict
    text_en: str
    text_hi: str


@dataclass
class LabFact:
    analyte: str
    value: str
    unit: str | None
    status: str


@dataclass
class IntakeFacts:
    labs: list[LabFact] = field(default_factory=list)
    present_analytes: set[str] = field(default_factory=set)
    report_dates: list[str] = field(default_factory=list)
    medications: list[str] = field(default_factory=list)
    today: date = field(default_factory=date.today)


@dataclass
class SelectedQuestion:
    pattern_id: str
    category: str
    slot: str | None
    text_en: str
    text_hi: str
    priority: int


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_question_bank(path: str | Path = DEFAULT_BANK) -> list[Pattern]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        Pattern(id=p["id"], category=p.get("category", "standard_history"),
                priority=int(p.get("priority", 0)), trigger=p.get("trigger", {}),
                text_en=p.get("text_en", ""), text_hi=p.get("text_hi", ""))
        for p in data.get("patterns", [])
    ]


def parse_date(text: str) -> date | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    d, mth, y = (int(g) for g in m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def _months_between(later: date, earlier: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _latest_date(dates: list[str]) -> date | None:
    parsed = [d for d in (parse_date(x) for x in dates) if d is not None]
    return max(parsed) if parsed else None


def _match_lab(facts: IntakeFacts, analytes: list[str], statuses: list[str]) -> LabFact | None:
    wanted = {_norm(a) for a in analytes}
    ok = {_norm(s) for s in statuses}
    for lab in facts.labs:
        if _norm(lab.analyte) in wanted and _norm(lab.status) in ok:
            return lab
    return None


def _slots_from_lab(lab: LabFact) -> dict:
    return {"analyte": lab.analyte, "value": lab.value, "unit": lab.unit or "", "status": lab.status}


def evaluate(patterns: list[Pattern], facts: IntakeFacts,
             stale_report_months: int = 6) -> list[tuple[Pattern, dict, str | None]]:
    """Return [(pattern, slots, slot_label)] for every pattern whose trigger fires."""
    matched: list[tuple[Pattern, dict, str | None]] = []
    for p in patterns:
        t = p.trigger or {}
        ttype = t.get("type")
        slots: dict = {}
        slot_label: str | None = None

        if ttype == "always":
            pass
        elif ttype == "danger_sign":
            # Antenatal danger-sign screen: always asked (like `always`), but
            # NOT a generic filler — select() ranks these as grounded so they are
            # never capped away. A "yes" is escalated to a red flag by
            # stages/maternal_risk.py (pattern ids start with "danger_").
            pass
        elif ttype == "lab_status":
            lab = _match_lab(facts, t.get("analytes", []), t.get("statuses", []))
            if not lab:
                continue
            slots = _slots_from_lab(lab)
            slot_label = lab.analyte
        elif ttype == "lab_flag_any":
            # Generic grounded catch-all: emit ONE question per flagged lab so no
            # clinically-tracked abnormal value in the report goes unasked, even
            # when it has no hand-written pattern. Scoped to an explicit analyte
            # allowlist (the clinically-askable set — excludes indices like MCV /
            # RDW / WBC that aren't patient-actionable) and to the given statuses.
            # select() drops any analyte already covered by a specific pattern, so
            # the well-worded question always wins over this fallback.
            allow = {_norm(a) for a in t.get("analytes", [])}
            stset = {_norm(s) for s in t.get("statuses", [])}
            for lab in facts.labs:
                if allow and _norm(lab.analyte) not in allow:
                    continue
                if _norm(lab.status) not in stset:
                    continue
                matched.append((p, _slots_from_lab(lab), lab.analyte))
            continue
        elif ttype == "missing_test":
            need = _norm(t.get("need", ""))
            if need in facts.present_analytes:
                continue
            trigger_lab = _match_lab(facts, t.get("when_analytes", []),
                                     t.get("when_statuses", []))
            if not trigger_lab:
                continue
            slots = _slots_from_lab(trigger_lab)
            slot_label = t.get("need")
        elif ttype == "stale_report":
            latest = _latest_date(facts.report_dates)
            if latest is None or _months_between(facts.today, latest) < stale_report_months:
                continue
            slots = {"date": latest.strftime("%d/%m/%Y")}
            slot_label = "date"
        elif ttype == "has_medication":
            if not facts.medications:
                continue
            slots = {"drug": facts.medications[0]}
            slot_label = facts.medications[0]
        else:
            continue

        matched.append((p, slots, slot_label))
    return matched


def _render_template(template: str, slots: dict) -> str:
    try:
        return template.format(**slots).replace("  ", " ").strip()
    except (KeyError, IndexError):
        # A template referenced a slot we could not fill: skip filling rather than
        # emit a broken/undefined question (guardrail — never surface a stray slot).
        return template


def looks_medical(facts: IntakeFacts) -> bool:
    """Whether the extracted data looks like a lab/medical report at all.

    True only if the document yielded at least one recognised lab value or a
    named medication. A report date alone is NOT enough — any dated document
    (an invoice, a software spec) has one. This is the signal that gates both
    the pipeline halt (server) and question generation: a non-medical document
    must never drive a spoken patient interview.
    """
    return bool(facts.labs or facts.present_analytes or facts.medications)


def select(patterns: list[Pattern], facts: IntakeFacts, max_questions: int = 5,
           stale_report_months: int = 6, max_standard: int = 2,
           max_grounded: int = 3) -> list[SelectedQuestion]:
    """Fire triggers and pick questions, grounded (report-specific) ones first.

    Strict guardrail: a document with no recognised clinical content gets ZERO
    questions — the ``always`` standard-history patterns are fillers for a REAL
    report, not licence to interrogate a patient about a non-medical document.

    Grounded questions (bound to this report's flagged values / meds / gaps) are
    always ranked ahead of the generic ``always`` fillers, and the fillers are
    capped (``max_standard``) so they can't dominate — otherwise two different
    reports whose grounded triggers differ would still tail into the same five
    generic questions.

    Antenatal mode (any ``danger_sign`` pattern fires): the danger-sign screen is
    a MANDATORY, reserved bucket. It is always asked in full AND kept out of the
    grounded budget — otherwise the five high-priority danger signs consume every
    slot and the report-specific follow-ups (anaemia, high BP, proteinuria, …)
    never get asked, so every report yields the identical question set. Here we
    ask: all danger signs + up to ``max_grounded`` report-specific follow-ups +
    a generic filler ONLY when nothing grounded fired (so a normal report still
    gets the "anything else?" prompt without padding a flagged one).
    """
    if not looks_medical(facts):
        return []

    matched = evaluate(patterns, facts, stale_report_months)
    danger = [m for m in matched if (m[0].trigger or {}).get("type") == "danger_sign"]
    fillers = [m for m in matched if (m[0].trigger or {}).get("type") == "always"]

    # Grounded = report-specific. Split into SPECIFIC (hand-written per-condition
    # patterns) and GENERIC (the lab_flag_any catch-all, one match per flagged
    # lab). A specific pattern always wins over the generic fallback for the same
    # analyte, and the generic ones fill in every OTHER flagged value so nothing
    # relevant in the report goes unasked.
    def _gtype(m):
        return (m[0].trigger or {}).get("type")

    specific = [m for m in matched if _gtype(m) not in ("always", "danger_sign", "lab_flag_any")]
    generic = [m for m in matched if _gtype(m) == "lab_flag_any"]
    specific.sort(key=lambda m: m[0].priority, reverse=True)

    # An analyte is "covered" (so the generic fallback skips it) if a specific
    # pattern matched it OR lists it among its trigger analytes — this stops a
    # second, redundant generic question for a sibling analyte (e.g. the sugar
    # pattern owns fasting + post-prandial + random sugar as one condition).
    covered: set[str] = set()
    for m in specific:
        if m[2]:
            covered.add(_norm(m[2]))
        if (m[0].trigger or {}).get("type") == "lab_status":
            for a in (m[0].trigger or {}).get("analytes", []):
                covered.add(_norm(a))
    deduped: list = []
    seen: set[str] = set()
    for m in generic:
        key = _norm(m[2] or "")
        if not key or key in covered or key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    deduped.sort(key=lambda m: m[0].priority, reverse=True)
    grounded = specific + deduped  # specific (well-worded) first, then generic fallback
    danger.sort(key=lambda m: m[0].priority, reverse=True)
    fillers.sort(key=lambda m: m[0].priority, reverse=True)

    if danger:
        chosen = list(danger) + grounded[:max_grounded]
        if not grounded:
            chosen += fillers[:max_standard]
    else:
        chosen = grounded[:max_questions]
        room = max_questions - len(chosen)
        if room > 0:
            chosen += fillers[: min(room, max_standard)]

    out: list[SelectedQuestion] = []
    for p, slots, slot_label in chosen:
        out.append(SelectedQuestion(
            pattern_id=p.id, category=p.category, slot=slot_label,
            text_en=_render_template(p.text_en, slots),
            text_hi=_render_template(p.text_hi, slots),
            priority=p.priority,
        ))
    return out


def validate_from_bank(pattern_id: str, patterns: list[Pattern]) -> bool:
    """Guardrail: a question is legal only if its pattern_id is in the bank."""
    return any(p.id == pattern_id for p in patterns)
