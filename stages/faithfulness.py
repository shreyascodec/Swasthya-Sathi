"""Faithfulness checker — the safety gate for Summary Generation (Phase 4).

Verifies that every value in a generated summary traces back to an OCR field.
Any numeric/medical value that does not appear in the source OCR is a
hallucination and is reported (and dropped/flagged by the stage). This is the
concrete enforcement of the product's faithfulness invariant, and the metric the
model bake-off headlines.

Pure and deterministic — no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.context import OCRField
from stages.interpret_rules import (
    ReferenceTable, load_reference_table, normalize_analyte,
)
from stages.summary_schema import SummarySchema

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _numbers(s: str) -> set[str]:
    return set(_NUM_RE.findall(s or ""))


@dataclass
class FaithIssue:
    kind: str          # hallucinated_value | bad_source | narrative_hallucination | med_not_found
    detail: str


@dataclass
class FaithfulnessReport:
    total_values: int
    traced_values: int
    issues: list[FaithIssue] = field(default_factory=list)

    @property
    def faithfulness(self) -> float:
        return 1.0 if self.total_values == 0 else self.traced_values / self.total_values

    @property
    def hallucination_rate(self) -> float:
        return 1.0 - self.faithfulness

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0


def _build_index(ocr_fields: list[OCRField]) -> tuple[set[str], set[str], set[str]]:
    """Return (value_strings, all_numbers, field_names) normalized for lookup."""
    values: set[str] = set()
    numbers: set[str] = set()
    names: set[str] = set()
    for f in ocr_fields:
        values.add(_norm(f.value))
        numbers |= _numbers(f.value)
        names.add(_norm(f.name))
    return values, numbers, names


# --- value <-> analyte binding ------------------------------------------------
# The original gate pooled every number on the report and asked "does this number
# appear ANYWHERE?". It therefore accepted a value lifted from a DIFFERENT
# analyte at faithfulness=1.00 — e.g. potassium's 4.63 reported as hemoglobin,
# which is a fabricated severe anemia. On a 16-page session (~59 values) the pool
# is large enough that almost any plausible number passes.
#
# Binding asks the correct question instead: is there an OCR field whose NAME is
# this analyte AND whose VALUE is this value?
#
# Analyte names are matched through interpret_rules.normalize_analyte, so the
# same identity guard applies here: "Urine Creatinine" can never bind to the
# serum "Creatinine" field, and "Serum Sodium" on the report does bind to
# "Sodium" in the summary.

#: Reference-table paths tried in order; the first that exists becomes the
#: synonym authority. Falls back to no table (string normalization only), so a
#: missing file degrades to the stricter behaviour rather than crashing.
_TABLE_CANDIDATES = (
    "data/labqar/reference_ranges_labqar.yaml",
    "data/labqar/reference_ranges.yaml",
)


@lru_cache(maxsize=1)
def _synonym_table() -> ReferenceTable | None:
    """The curated alias table, used to decide when two names are ONE analyte.

    String normalization alone cannot bridge 'Haemoglobin'/'Hemoglobin',
    'PCV'/'Hematocrit' or 'S.G.O.T'/'Aspartate aminotransferase' — those are
    SYNONYM relations, and the curated (clinician-reviewable) alias sets are
    exactly where that knowledge already lives. Measured on the real bench
    reports, binding without this rejected 18 of 63 legitimate findings whenever
    the summary used an analyte's canonical name instead of echoing OCR.

    This deliberately reuses the same table the interpret stage trusts, so the
    identity guard carries over: 'Urine Creatinine' has no entry, gets no
    canonical key, and therefore still cannot bind to serum 'Creatinine'.
    """
    root = Path(__file__).resolve().parent.parent
    for rel in _TABLE_CANDIDATES:
        path = root / rel
        if path.exists():
            table = load_reference_table(path)
            if table.by_alias:
                return table
    return None


def _analyte_keys(name: str) -> set[str]:
    """Every lookup key a name may legitimately match.

    Two names bind when their key sets intersect. When the curated table
    resolves a name, its canonical key is the ONLY key we expose; string
    normalization is the fallback for names the table does not know.

    Exposing both was a hole. `normalize_analyte` strips a trailing
    parenthetical gloss, so "Thyroxine (FT4)" and "Thyroxine (T4)" both reduce
    to the stem "thyroxine" — and a free-T4 value reported as total T4 bound
    clean at faithfulness 1.00, despite the two having different units (ng/dL vs
    µg/dL) and non-overlapping intervals (0.9-2.3 vs 5.5-12.5). Same for
    FT3/T3, and for T3 against the bare "Triiodothyronine" uptake row. Deferring
    to the canonical key means identity is decided by the clinician-reviewable
    table rather than by a shared stem.
    """
    base = _norm(name)
    if not base:
        return set()
    table = _synonym_table()
    if table is not None:
        entry = table.lookup(name)
        if entry and entry.get("canonical"):
            # Namespaced so a canonical name can never collide with a raw
            # string key from an unrelated analyte.
            return {"canonical:" + _norm(entry["canonical"])}
    return {base} | {k for k in normalize_analyte(name) if k}


def _values_agree(field_value: str, claimed: str) -> bool:
    """True if `claimed` is supported by THIS field's value (never a global pool)."""
    if _norm(field_value) == _norm(claimed):
        return True
    claimed_nums = _numbers(claimed)
    return bool(claimed_nums) and claimed_nums.issubset(_numbers(field_value))


def bind_field(analyte: str, value: str, ocr_fields: list[OCRField]) -> OCRField | None:
    """The OCR field that supports `analyte = value`, or None."""
    keys = _analyte_keys(analyte)
    if not keys:
        return None
    for f in ocr_fields:
        if keys & _analyte_keys(f.name) and _values_agree(f.value, value):
            return f
    return None


def analyte_present(analyte: str, ocr_fields: list[OCRField]) -> bool:
    """True if the report mentions this analyte at all (regardless of value).

    Distinguishes "wrong value for a real analyte" (misattribution) from
    "analyte is not on this report at all" (fabrication).
    """
    keys = _analyte_keys(analyte)
    return bool(keys) and any(keys & _analyte_keys(f.name) for f in ocr_fields)


def _unit_conflict(claimed: str | None, field_unit: str | None) -> bool:
    """Units disagree. Absent on either side is not a conflict — many OCR rows
    carry no unit and refusing those would reject legitimate findings."""
    if not claimed or not field_unit:
        return False
    return _norm(claimed).replace(" ", "") != _norm(field_unit).replace(" ", "")


#: Shorter than this a "medication name" cannot be matched safely: substring
#: matching traced a medication called "m" to "Tab Metformin 500mg".
_MIN_MED_CHARS = 3


def _med_traced(name: str, ocr_fields: list[OCRField]) -> bool:
    """Whole-token match against OCR values — not a substring test."""
    nm = _norm(name)
    if len(nm) < _MIN_MED_CHARS:
        return False
    pattern = re.compile(rf"\b{re.escape(nm)}\b")
    for f in ocr_fields:
        if pattern.search(_norm(f.value)) or pattern.search(_norm(f.name)):
            return True
    return False


def check_faithfulness(summary: SummarySchema | dict, ocr_fields: list[OCRField]) -> FaithfulnessReport:
    if isinstance(summary, dict):
        summary = SummarySchema.model_validate(summary)

    ocr_values, ocr_numbers, ocr_names = _build_index(ocr_fields)
    issues: list[FaithIssue] = []
    total = 0
    traced = 0

    def value_traced(value: str) -> bool:
        nv = _norm(value)
        if nv in ocr_values:
            return True
        nums = _numbers(value)
        return bool(nums) and nums.issubset(ocr_numbers)

    for finding in summary.lab_findings:
        total += 1
        bound = bind_field(finding.analyte, finding.value, ocr_fields)
        if bound is not None:
            traced += 1
            if _unit_conflict(finding.unit, bound.unit):
                issues.append(FaithIssue(
                    "unit_mismatch",
                    f"{finding.analyte}: summary says '{finding.unit}' but OCR "
                    f"field '{bound.name}' says '{bound.unit}'"))
        elif analyte_present(finding.analyte, ocr_fields):
            # The analyte IS on the report but carries a different value: the
            # value was lifted from elsewhere. Clinically the worst case, and
            # invisible to the old global-pool check.
            issues.append(FaithIssue(
                "value_analyte_mismatch",
                f"{finding.analyte}={finding.value} does not match this "
                f"analyte's OCR value"))
        else:
            issues.append(FaithIssue("hallucinated_value",
                                     f"{finding.analyte}={finding.value} not in OCR"))
        # A finding may legitimately cite MORE than one OCR field — the value and
        # its ref-range partner are two separate fields ("Hemoglobin, Hemoglobin
        # ref-range"), and citing both is better provenance, not worse. Accept a
        # comma-separated citation as long as every part names a real field.
        if finding.source_field and finding.source_field != "unknown":
            cited = [c.strip() for c in str(finding.source_field).split(",") if c.strip()]
            missing = [c for c in cited if _norm(c) not in ocr_names]
            if missing:
                issues.append(FaithIssue(
                    "bad_source",
                    f"{finding.analyte} cites missing field "
                    f"'{', '.join(missing)}'"))
        if finding.ref_range:
            total += 1
            if value_traced(finding.ref_range):
                traced += 1
            else:
                issues.append(FaithIssue("hallucinated_value",
                                         f"{finding.analyte} ref-range {finding.ref_range} not in OCR"))

    for med in summary.medications:
        total += 1
        if _med_traced(med.name, ocr_fields):
            traced += 1
        else:
            issues.append(FaithIssue("med_not_found", f"medication '{med.name}' not in OCR"))

    # Narrative numbers must also be grounded (catches numbers invented in prose).
    for narrative in (summary.narrative_en,):
        for num in _numbers(narrative):
            total += 1
            if num in ocr_numbers:
                traced += 1
            else:
                issues.append(FaithIssue("narrative_hallucination",
                                         f"narrative contains ungrounded number '{num}'"))

    return FaithfulnessReport(total_values=total, traced_values=traced, issues=issues)


def reconcile_multimodal(
    summary: SummarySchema, ocr_fields: list[OCRField]
) -> tuple[SummarySchema, list[dict]]:
    """Multimodal reconciliation for the text+IMAGE path.

    A vision model can legitimately read values off the report image that OCR
    missed. We must neither silently trust those (they aren't cross-checkable
    against OCR) nor silently drop them (that throws away real recoveries). So:

      * findings that trace to an OCR field stay in ``lab_findings`` as VERIFIED;
      * findings that do not trace to OCR are pulled OUT of ``lab_findings`` and
        returned as an ``unverified_image_findings`` review list — surfaced to the
        clinician, never presented as verified, never auto-interpreted.

    The stored ``lab_findings`` therefore remains OCR-faithful (same invariant as
    the text path), so the interpret stage only ever flags verified values.
    """
    ocr_values, ocr_numbers, ocr_names = _build_index(ocr_fields)

    def traced(value: str) -> bool:
        nv = _norm(value)
        if nv in ocr_values:
            return True
        nums = _numbers(value)
        return bool(nums) and nums.issubset(ocr_numbers)

    verified = []
    unverified: list[dict] = []
    for f in summary.lab_findings:
        if bind_field(f.analyte, f.value, ocr_fields) is not None:
            verified.append(f)
        else:
            unverified.append({
                "analyte": f.analyte, "value": f.value, "unit": f.unit,
                "ref_range": f.ref_range, "source": "image", "needs_review": True,
            })

    cleaned = summary.model_copy(update={"lab_findings": verified})
    return cleaned, unverified


def drop_hallucinations(summary: SummarySchema, ocr_fields: list[OCRField]) -> SummarySchema:
    """Return a copy with untraceable lab findings/medications removed and their
    names moved to ``unknowns`` — so the stored summary is always faithful."""
    ocr_values, ocr_numbers, ocr_names = _build_index(ocr_fields)

    def traced(value: str) -> bool:
        nv = _norm(value)
        if nv in ocr_values:
            return True
        nums = _numbers(value)
        return bool(nums) and nums.issubset(ocr_numbers)

    kept_findings = []
    unknowns = list(summary.unknowns)
    for f in summary.lab_findings:
        # Binding, not the global number pool: a value borrowed from another
        # analyte is dropped exactly like an invented one.
        if bind_field(f.analyte, f.value, ocr_fields) is not None:
            kept_findings.append(f)
        else:
            unknowns.append(f.analyte)

    kept_meds = []
    for m in summary.medications:
        if _med_traced(m.name, ocr_fields):
            kept_meds.append(m)
        else:
            unknowns.append(m.name)

    return summary.model_copy(update={
        "lab_findings": kept_findings,
        "medications": kept_meds,
        "unknowns": unknowns,
    })
