"""Rule-based lab interpretation for Stage [5] — pure, deterministic, no model.

Compares each extracted lab value against a reference interval and returns a
status in {low, normal, high, critical, unknown}. The reference interval comes
from the LabQAR table (sex-aware when known); if an analyte is not in the table
we fall back to the report's own PRINTED reference range. Anything we cannot
compare cleanly (missing/garbled value, unit mismatch, no range) is left
``unknown`` and flagged for review — never guessed.

Hard invariants (ARCHITECTURE / PLAN):
  * No model, no reasoning — lookup + numeric comparison only.
  * Output is a STATUS, never a diagnosis and never an autonomous escalation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_TABLE = Path(__file__).resolve().parent.parent / "data" / "labqar" / "reference_ranges.yaml"

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
# Ranges use UNSIGNED numbers: the '-' in "13.0-17.0" is a separator, not a sign
# (lab magnitudes are never negative), so a signed pattern would mis-split it.
_UNSIGNED = re.compile(r"\d+(?:\.\d+)?")
_STATUSES = ("low", "normal", "high", "critical", "unknown")


@dataclass
class RefInterval:
    low: float | None = None
    high: float | None = None
    crit_low: float | None = None
    crit_high: float | None = None
    unit: str | None = None
    direction: str | None = None      # None | "high_only" | "low_only"
    source: str = "labqar"            # labqar | printed | none

    @property
    def usable(self) -> bool:
        """True if this interval can actually decide a status.

        An interval with no bound on either side compares vacuously: every
        `low_ok`/`high_ok` test passes and the value is declared ``normal``. A
        table row that exists but carries no range must therefore NOT count as a
        hit — see resolve_interval.
        """
        return any(b is not None
                   for b in (self.low, self.high, self.crit_low, self.crit_high))


@dataclass
class Interpretation:
    analyte: str
    value: str
    unit: str | None
    ref_range: str | None
    status: str = "unknown"
    high_priority: bool = False
    needs_review: bool = False
    review_reason: str | None = None


# --- analyte-name normalization ----------------------------------------------
# Real OCR prints an analyte with a specimen prefix, an abbreviation dot pattern
# or a plural: "Serum Chlorides", "S.G.O.T", "Blood Urea", "IONIC CALCIUM".
# Exact alias lookup misses every one of them.
#
# This is DETERMINISTIC normalization, not similarity matching. It only ever
# removes tokens from a fixed whitelist; it never scores, never guesses, and a
# name that does not normalize to a known alias stays `unknown` exactly as
# before. (Similarity/fuzzy matching is deliberately NOT done here — see
# nlpplan.md: "HDL cholesterol" scores 95 against "Total Cholesterol" and would
# silently apply the wrong reference range.)

#: Specimen prefixes that do not change WHICH analyte is meant. "Serum Sodium"
#: and "Sodium" are the same measurement against the same interval.
_SPECIMEN_PREFIXES = ("serum", "sr", "s", "plasma", "blood", "b")

#: Tokens that DO change the analyte's identity or its reference interval.
#: If any appears, normalization is refused outright and the name must match an
#: explicit alias. Stripping these would silently swap in the wrong range:
#:   urine creatinine  != serum creatinine   (different interval entirely)
#:   free T4           != T4
#:   direct/indirect bilirubin != total bilirubin
#:   ionic calcium     != total calcium      (different unit AND interval)
#:   fasting/random glucose are different intervals
#: HDL/LDL/VLDL are listed for the same reason they are guarded elsewhere.
#: ``ft3``/``ft4`` are listed because free-ness is often encoded in the
#: ABBREVIATION rather than spelled out: "Thyroxine (FT4)" carries no "free"
#: token, yet it is not "Thyroxine (T4)" — different unit, non-overlapping
#: interval.
_IDENTITY_TOKENS = (
    "urine", "urinary", "csf", "fluid", "24 hr", "24hr", "24 hour",
    "free", "direct", "indirect", "conjugated", "unconjugated",
    "ionic", "ionised", "ionized",
    "fasting", "random", "post prandial", "postprandial", "pp",
    "hdl", "ldl", "vldl", "ft3", "ft4",
)

# Matched on WORD boundaries, not as bare substrings. Substring matching refused
# to normalize 20 legitimate LabQAR names — "Taurine" tripped "urine", "Copper"
# tripped "pp", "hCG" tripped "ionic", "VLDL" tripped "ldl". Every name that
# SHOULD be refused carries its own explicit token ("indirect", "unconjugated"
# and "vldl" are all listed), so nothing loses its guard.
_IDENTITY_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _IDENTITY_TOKENS) + r")\b"
)


@dataclass
class ReferenceTable:
    by_alias: dict[str, dict] = field(default_factory=dict)
    version: str = "none"
    #: (alias, losing canonical, winning canonical) for every alias claimed by
    #: two different analytes. Surfaced so a curation error in the YAML is
    #: reviewable instead of silent.
    collisions: list[tuple[str, str, str]] = field(default_factory=list)

    def lookup(self, analyte: str) -> dict | None:
        """Exact alias hit first; deterministic normalization only as fallback."""
        hit = self.by_alias.get(_norm(analyte))
        if hit is not None:
            return hit
        for candidate in normalize_analyte(analyte):
            hit = self.by_alias.get(candidate)
            if hit is not None:
                return hit
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def normalize_analyte(analyte: str) -> list[str]:
    """Deterministic lookup candidates for an OCR'd analyte name.

    Returns progressively-normalized forms, most conservative first. Returns []
    when the name carries an identity-changing token (§_IDENTITY_TOKENS), so a
    urine or free/direct fraction can never fall through to the serum/total
    entry. Pure and side-effect free.
    """
    base = _norm(analyte)
    if not base:
        return []
    if _IDENTITY_TOKEN_RE.search(base):
        return []

    out: list[str] = []

    def push(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip(" .,:-")
        if value and value not in out and value != base:
            out.append(value)

    # "S.G.O.T" -> "sgot", "R.B.C. Count" -> "rbc count"
    dotless = re.sub(r"\b([a-z])\.(?=[a-z]\b|\s|$)", r"\1", base)
    dotless = re.sub(r"\s+", " ", dotless.replace(".", " ")).strip()
    push(dotless)

    for form in list(out) + [base]:
        # Drop a trailing abbreviation gloss: "Packed Cell Volume (PCV)".
        # Safe because _IDENTITY_TOKENS already rejected discriminating
        # parentheticals such as "Blood Sugar (R)".
        no_paren = re.sub(r"\s*\([^)]*\)\s*$", "", form).strip()
        push(no_paren)

        for candidate in {form, no_paren}:
            # Specimen prefix: "Serum Chlorides" -> "chlorides".
            parts = candidate.split()
            if len(parts) >= 2 and parts[0] in _SPECIMEN_PREFIXES:
                push(" ".join(parts[1:]))
            # Plural: "Chlorides" -> "Chloride".
            if candidate.endswith("s") and not candidate.endswith("ss"):
                push(candidate[:-1])
                p2 = candidate[:-1].split()
                if len(p2) >= 2 and p2[0] in _SPECIMEN_PREFIXES:
                    push(" ".join(p2[1:]))

    return out


def _entry_has_range(entry: dict) -> bool:
    """True if a YAML row carries at least one usable bound (see RefInterval.usable)."""
    default = entry.get("default") or {}
    if default.get("low") is not None or default.get("high") is not None:
        return True
    for rng in (entry.get("by_sex") or {}).values():
        if (rng or {}).get("low") is not None or (rng or {}).get("high") is not None:
            return True
    crit = entry.get("critical") or {}
    return crit.get("low") is not None or crit.get("high") is not None


def load_reference_table(path: str | Path = DEFAULT_TABLE) -> ReferenceTable:
    """Load the LabQAR YAML table into an alias-indexed lookup.

    (An xlsx loader can populate the same structure later; the rest of the stage
    is agnostic to where the ranges came from.)
    """
    path = Path(path)
    if not path.exists():
        return ReferenceTable(version="missing")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_alias: dict[str, dict] = {}
    collisions: list[tuple[str, str, str]] = []
    for entry in data.get("analytes", []):
        keys = set(entry.get("aliases", [])) | {entry.get("canonical", "")}
        for k in keys:
            if not k:
                continue
            kn = _norm(k)
            prev = by_alias.get(kn)
            if prev is not None and prev is not entry:
                # Last-write-wins silently dropped a populated row: a bare
                # placeholder for "Glycated hemoglobin" claimed the alias
                # 'hba1c' and displaced the real 4.0-5.6 % / high_only entry,
                # after which every HbA1c read back as normal. A row carrying an
                # actual range always outranks one that doesn't.
                keep_prev = _entry_has_range(prev) or not _entry_has_range(entry)
                winner, loser = (prev, entry) if keep_prev else (entry, prev)
                collisions.append((kn, str(loser.get("canonical", "")),
                                   str(winner.get("canonical", ""))))
                if keep_prev:
                    continue
            by_alias[kn] = entry
    return ReferenceTable(by_alias=by_alias, collisions=collisions,
                          version=str(data.get("version", "poc")))


def parse_printed_range(text: str | None) -> tuple[float | None, float | None]:
    """Parse a printed reference range like '13.0-17.0', '< 200', '0 - 150'.

    Returns (low, high); either may be None for one-sided ranges.
    """
    if not text:
        return (None, None)
    t = text.strip()
    if t.startswith("<") or t.lower().startswith("upto") or t.lower().startswith("up to"):
        nums = _UNSIGNED.findall(t)
        return (None, float(nums[0])) if nums else (None, None)
    if t.startswith(">"):
        nums = _UNSIGNED.findall(t)
        return (float(nums[0]), None) if nums else (None, None)
    nums = _UNSIGNED.findall(t)
    if len(nums) >= 2:
        lo, hi = float(nums[0]), float(nums[1])
        return (min(lo, hi), max(lo, hi))
    if len(nums) == 1:
        return (None, float(nums[0]))
    return (None, None)


def _interval_from_table(entry: dict, sex: str | None) -> RefInterval:
    rng = entry.get("default", {})
    if sex and entry.get("by_sex", {}).get(_norm(sex)):
        rng = entry["by_sex"][_norm(sex)]
    crit = entry.get("critical", {})
    return RefInterval(
        low=rng.get("low"), high=rng.get("high"),
        crit_low=crit.get("low"), crit_high=crit.get("high"),
        unit=entry.get("unit"), direction=entry.get("direction"),
        source="labqar",
    )


def resolve_interval(analyte: str, printed_ref: str | None, table: ReferenceTable,
                     sex: str | None = None) -> RefInterval:
    """Prefer the LabQAR table; fall back to the report's printed range.

    A table row that exists but carries NO bounds is not a hit. Treating it as
    one is how an HbA1c of 9.8 % came back ``normal``: the row was found, so the
    caller skipped the ``source == "none"`` bail-out, and a bound-less interval
    compares vacuously in both directions. Such rows now fall through to the
    printed range, and to ``unknown`` when there isn't one — which is what the
    module's "never guessed" invariant requires.
    """
    entry = table.lookup(analyte)
    if entry:
        interval = _interval_from_table(entry, sex)
        if interval.usable:
            return interval
    lo, hi = parse_printed_range(printed_ref)
    if lo is not None or hi is not None:
        return RefInterval(low=lo, high=hi, source="printed")
    return RefInterval(source="none")


def _to_float(value: str) -> float | None:
    m = _NUM.search(value or "")
    return float(m.group()) if m else None


def _unit_mismatch(value_unit: str | None, ref_unit: str | None) -> bool:
    if not value_unit or not ref_unit:
        return False
    return _norm(value_unit).replace(" ", "") != _norm(ref_unit).replace(" ", "")


def interpret_value(analyte: str, value: str, unit: str | None,
                    printed_ref: str | None, table: ReferenceTable,
                    sex: str | None = None,
                    high_priority_statuses: tuple[str, ...] = ("critical",)) -> Interpretation:
    """Interpret one lab value into a status. Pure and deterministic."""
    interp = Interpretation(analyte=analyte, value=value, unit=unit, ref_range=printed_ref)

    num = _to_float(value)
    if num is None:
        interp.status = "unknown"
        interp.needs_review = True
        interp.review_reason = "unparseable_value"
        return interp

    interval = resolve_interval(analyte, printed_ref, table, sex)
    if interval.source == "none":
        interp.status = "unknown"
        interp.needs_review = True
        interp.review_reason = "no_reference_range"
        return interp

    # Unit mismatch: we will not compare across units silently.
    if interval.source == "labqar" and _unit_mismatch(unit, interval.unit):
        interp.status = "unknown"
        interp.needs_review = True
        interp.review_reason = f"unit_mismatch(value={unit} vs ref={interval.unit})"
        return interp

    # Show which range was actually used (esp. when it came from LabQAR).
    if interval.source == "labqar":
        if interval.low is not None and interval.high is not None:
            interp.ref_range = f"{interval.low}-{interval.high}"
        elif interval.high is not None:
            interp.ref_range = f"<{interval.high}"
        elif interval.low is not None:
            interp.ref_range = f">{interval.low}"

    # Critical panic thresholds first (only where defined).
    if interval.crit_low is not None and num <= interval.crit_low:
        interp.status = "critical"
    elif interval.crit_high is not None and num >= interval.crit_high:
        interp.status = "critical"
    else:
        # Direction gates one-sided analytes so e.g. a high Vitamin D isn't "high".
        low_ok = interval.low is None or num >= interval.low or interval.direction == "high_only"
        high_ok = interval.high is None or num <= interval.high or interval.direction == "low_only"
        if not high_ok:
            interp.status = "high"
        elif not low_ok:
            interp.status = "low"
        else:
            interp.status = "normal"

    interp.high_priority = interp.status in high_priority_statuses
    return interp
