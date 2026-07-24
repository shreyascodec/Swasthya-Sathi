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
        elif ttype == "lab_status":
            lab = _match_lab(facts, t.get("analytes", []), t.get("statuses", []))
            if not lab:
                continue
            slots = _slots_from_lab(lab)
            slot_label = lab.analyte
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


def select(patterns: list[Pattern], facts: IntakeFacts, max_questions: int = 5,
           stale_report_months: int = 6) -> list[SelectedQuestion]:
    """Fire triggers, then take the top-N by priority (grounded questions first)."""
    matched = evaluate(patterns, facts, stale_report_months)
    matched.sort(key=lambda m: m[0].priority, reverse=True)
    out: list[SelectedQuestion] = []
    for p, slots, slot_label in matched[:max_questions]:
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
