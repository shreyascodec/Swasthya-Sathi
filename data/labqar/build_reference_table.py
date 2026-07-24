"""Convert the LabQAR 550-row LOINC-mapped xlsx into the interpretation table.

Reads the published supplementary xlsx (Scientific Data 41597_2026_7554_MOESM2)
and emits `reference_ranges_labqar.yaml` in the schema `stages/interpret_rules.py`
already consumes — so the interpretation stage stays pure lookup + comparison.

WHY A GENERATED YAML (not a runtime xlsx parser):
  * The architecture requires a clinician review pass before these ranges are
    trusted. A diffable, commented YAML is reviewable; a binary xlsx is not.
  * No new runtime dependency (openpyxl stays a build-time tool).
  * Reverting is a config edit (`interpret.reference_path`).

CLINICAL SAFETY RULES ENCODED HERE (each one exists to avoid a wrong flag):
  1. Only `Types of reference range == "Normal"` rows become reference intervals.
     Therapeutic/Toxic/Legal-intoxication rows describe drug monitoring, NOT
     normality — comparing a patient value against a "Therapeutic" band would
     mislabel healthy people.
  2. Rows carrying a condition we cannot observe at a kiosk (menstrual-cycle
     phase, posture, smoking status, fasting-specific states) are NOT used as a
     default interval. If an analyte has ONLY conditioned rows, it is emitted
     with `needs_context: true` and no default range, so the stage returns
     `unknown` + needs_review rather than guessing a phase.
  3. Sex-specific rows populate `by_sex`; the unconditioned row (if any) is the
     `default` used when sex is unknown.
  4. Curated POC entries win on `critical` panic thresholds, `direction`, and
     Indian-report `aliases` — the published table carries none of those, and
     dropping them would lose both patient-safety thresholds and OCR matching.

Usage:
    python data/labqar/build_reference_table.py <path-to-xlsx> [-o out.yaml]
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CURATED = HERE / "reference_ranges.yaml"
DEFAULT_OUT = HERE / "reference_ranges_labqar.yaml"

# Rule 1: only these row types describe "normal".
NORMAL_TYPES = {"normal"}

# Rule 2: conditions a kiosk cannot establish -> never a default interval.
UNOBSERVABLE_CONDITION = re.compile(
    r"follicular|luteal|midcycle|ovulat|menopaus|pregnan|smoker|nonsmoker|"
    r"upright|supine|recumbent|fasting|postprandial|peak|trough|stimulat",
    re.I,
)

_DASH = "–—−-"          # en/em dash, unicode minus, hyphen
_NUM = r"\d+(?:\.\d+)?"


def clean(s) -> str:
    """Normalize a cell: drop soft hyphens/NBSP, collapse whitespace."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    t = t.replace("­", "").replace("​", "")   # soft hyphen, ZWSP
    return re.sub(r"\s+", " ", t).strip()


# Greek letters are spelled out on Indian lab reports ("Gamma GT", "Beta hCG").
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa",
         "λ": "lambda", "μ": "mu", "ω": "omega"}


def norm_key(s: str) -> str:
    """Lookup key: lowercase, punctuation-light (matches interpret_rules._norm)."""
    return re.sub(r"\s+", " ", clean(s).lower()).strip()


def despell_greek(s: str) -> str:
    """'γ-Glutamyltransferase' -> 'gamma-glutamyltransferase'."""
    out = s
    for g, word in GREEK.items():
        out = out.replace(g, word).replace(g.upper(), word)
    return out


def parse_interval(text: str) -> tuple[float | None, float | None]:
    """'15–70' -> (15,70) · '<70' -> (None,70) · '>400' -> (400,None)."""
    t = clean(text)
    if not t:
        return (None, None)
    # "Negative (<500)" / "Nonreactive (<1.0)" -> the parenthetical IS the range.
    m = re.fullmatch(r"(?:negative|nonreactive|non-reactive)\s*\(([^)]+)\)", t, re.I)
    if m:
        t = clean(m.group(1))
    if re.fullmatch(rf"[<≤]\s*{_NUM}", t):
        return (None, float(re.search(_NUM, t).group()))
    if re.fullmatch(rf"[>≥]\s*{_NUM}", t):
        return (float(re.search(_NUM, t).group()), None)
    m = re.fullmatch(rf"({_NUM})\s*[{_DASH}]\s*({_NUM})", t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    if re.fullmatch(_NUM, t):        # bare number: a point value, not a range
        return (None, None)
    return (None, None)


# Naming-only synonyms (NOT clinical assertions): the same analyte written the
# way an Indian lab report prints it vs. the way the published table names it.
NAME_SYNONYMS: dict[str, list[str]] = {
    "thyroxine (ft4)": ["free t4", "ft4", "free thyroxine"],
    "thyroxine (t4)": ["t4", "total t4"],
    "triiodothyronine (ft3)": ["free t3", "ft3", "free triiodothyronine"],
    "triiodothyronine (t3)": ["t3", "total t3"],
    "aspartate aminotransferase (ast, sgot)": ["sgot", "ast", "sgot/ast"],
    "alanine aminotransferase (alt, sgpt)": ["sgpt", "alt", "sgpt/alt"],
    "reticulocyte count": ["reticulocytes"],
    "leukocyte count": ["wbc", "total leucocyte count", "tlc", "white blood cell"],
    "platelet count": ["platelets", "plt"],
    "erythrocyte sedimentation rate": ["esr"],
    "γ-glutamyltransferase (ggt; γ-glutamyl transpeptidase)": [
        "ggt", "gamma glutamyl transferase", "gamma gt", "ggtp"],
}


def _variants(key: str) -> set[str]:
    """Spelling variants of one alias: hyphen/space, plural, trailing 'count'."""
    out = {key}
    out.add(key.replace("-", " "))
    out.add(key.replace("-", ""))
    for v in list(out):
        if v.endswith(" count"):
            out.add(v[: -len(" count")])
        if v.endswith("s") and len(v) > 4:
            out.add(v[:-1])
        else:
            out.add(v + "s")
    return {re.sub(r"\s+", " ", v).strip() for v in out if len(v) > 1}


def aliases_for(test_name: str) -> list[str]:
    """Derive match keys: full name, name w/o parenthetical, abbreviations,
    declared synonyms, and spelling variants of each."""
    name = clean(test_name)
    base = {norm_key(name)}
    # "Aspartate aminotransferase (AST, SGOT)" -> base + each abbreviation.
    m = re.match(r"^(.*?)\s*\(([^)]{1,60})\)\s*$", name)
    if m:
        base.add(norm_key(m.group(1)))
        for token in re.split(r"[;,]", m.group(2)):
            token = norm_key(token)
            if 1 < len(token) <= 40:
                base.add(token)
    # "SGPT/ALT" style -> both sides.
    for part in re.split(r"\s*/\s*", name):
        if 1 < len(part) <= 40:
            base.add(norm_key(part))
    base |= set(NAME_SYNONYMS.get(norm_key(name), []))

    for k in list(base):
        g = norm_key(despell_greek(k))
        if g != k:
            base.add(g)

    out: set[str] = set()
    for k in base:
        out |= _variants(k)
    return sorted(k for k in out if k)


def load_rows(xlsx: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [clean(h) for h in rows[0]]
    return [dict(zip(hdr, r)) for r in rows[1:]]


def build(rows: list[dict]) -> tuple[list[dict], dict]:
    stats = defaultdict(int)
    by_test: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        test = clean(r.get("Lab Test"))
        if not test:
            continue
        by_test[test].append(r)

    analytes: list[dict] = []
    for test, group in sorted(by_test.items()):
        normal = [r for r in group
                  if norm_key(r.get("Types of reference range")) in NORMAL_TYPES]
        stats["rows_total"] += len(group)
        if not normal:
            stats["tests_no_normal_range"] += 1        # rule 1
            continue

        def conditioned(r: dict) -> bool:              # rule 2
            blob = " ".join(clean(r.get(c)) for c in
                            ("Women-related condition", "Other condition"))
            return bool(UNOBSERVABLE_CONDITION.search(blob))

        unconditioned = [r for r in normal if not conditioned(r)]
        adult_ok = [r for r in unconditioned
                    if norm_key(r.get("Age group-specific")) in ("", "none", "adult")]
        usable = adult_ok or unconditioned

        entry: dict = {"canonical": test, "aliases": aliases_for(test)}
        loinc = clean(next((r.get("LOINC") for r in normal if clean(r.get("LOINC"))), ""))
        if loinc:
            entry["loinc"] = loinc
        specimen = clean(next((r.get("Specimen") for r in usable or normal), ""))
        if specimen:
            entry["specimen"] = specimen

        if not usable:
            # Only cycle-phase / posture / smoking-conditioned ranges exist.
            entry["needs_context"] = True
            entry["note"] = "only condition-specific ranges published; kiosk cannot establish condition"
            analytes.append(entry)
            stats["tests_needs_context"] += 1
            continue

        unit = clean(next((r.get("Traditional Units") for r in usable
                           if clean(r.get("Traditional Units"))), ""))
        if unit:
            entry["unit"] = unit

        by_sex: dict[str, dict] = {}
        default: dict | None = None
        for r in usable:
            lo, hi = parse_interval(r.get("Traditional Reference Interval"))
            if lo is None and hi is None:
                continue
            rng = {k: v for k, v in (("low", lo), ("high", hi)) if v is not None}
            sex = norm_key(r.get("Gender-specific"))
            if sex in ("male", "female"):
                by_sex.setdefault(sex, rng)
            elif default is None:
                default = rng

        if default is None and by_sex:
            # Sex-only table: widest span as the sex-unknown default (never narrower
            # than either sex, so we cannot flag someone on the wrong sex's range).
            lows = [v["low"] for v in by_sex.values() if "low" in v]
            highs = [v["high"] for v in by_sex.values() if "high" in v]
            default = {}
            if lows:
                default["low"] = min(lows)
            if highs:
                default["high"] = max(highs)
        if default is None:
            stats["tests_unparseable_range"] += 1
            continue

        entry["default"] = default
        if by_sex:
            entry["by_sex"] = by_sex
        analytes.append(entry)
        stats["tests_with_range"] += 1

    # Alias collisions: two analytes claiming one key would make lookup depend on
    # file order — a silent mis-mapping. Drop the contested key from BOTH (the
    # value then falls back to the report's printed range or `unknown`), and
    # report it. Never let an ambiguous name resolve to an arbitrary analyte.
    owners: dict[str, list[dict]] = defaultdict(list)
    for e in analytes:
        for a in e.get("aliases", []):
            owners[a].append(e)
    collisions = {k: [e["canonical"] for e in v] for k, v in owners.items() if len(v) > 1}
    for key, _ in collisions.items():
        for e in owners[key]:
            if key in e.get("aliases", []) and norm_key(e["canonical"]) != key:
                e["aliases"] = [a for a in e["aliases"] if a != key]
    stats["alias_collisions_dropped"] = len(collisions)

    return analytes, dict(stats), collisions


def _console_safe(text: str) -> str:
    """Drop characters the console encoding cannot represent.

    Analyte names carry Greek/µ characters ('17α-Hydroxyprogesterone'). On a
    Windows cp1252 console the diagnostic print raised UnicodeEncodeError and
    the script exited non-zero *after* correctly writing the YAML — a spurious
    build failure. The output file itself is always written UTF-8.
    """
    enc = sys.stdout.encoding or "utf-8"
    return text.encode(enc, errors="replace").decode(enc, errors="replace")


def merge_curated(generated: list[dict], curated_path: Path) -> tuple[list[dict], dict]:
    """Rule 4: curated critical thresholds / direction / Indian aliases win."""
    stats = defaultdict(int)
    if not curated_path.exists():
        return generated, dict(stats)
    curated = yaml.safe_load(curated_path.read_text(encoding="utf-8")) or {}
    cur_entries = curated.get("analytes", [])

    index: dict[str, dict] = {}
    for e in generated:
        for a in e.get("aliases", []):
            index.setdefault(a, e)

    for c in cur_entries:
        keys = [norm_key(k) for k in
                ([c.get("canonical", "")] + list(c.get("aliases", []))) if k]
        target = next((index[k] for k in keys if k in index), None)
        if target is None:
            # Curated analyte absent from the published table -> keep it as-is.
            merged = dict(c)
            merged["source"] = "curated-poc"
            generated.append(merged)
            stats["curated_only"] += 1
            continue
        target["aliases"] = sorted(set(target.get("aliases", [])) | set(keys))
        for field in ("critical", "direction"):
            if field in c:
                target[field] = c[field]
                stats[f"curated_{field}_applied"] += 1
        # Curated ranges are Indian-report tuned; keep them and record the
        # published interval alongside for the clinician review pass.
        # A range and its unit are ONE package: taking the curated interval
        # (e.g. WBC 4000-11000 /cumm) while keeping the published unit
        # (10^3 uL-1) would pair a range with the wrong scale.
        if "default" in c:
            if target.get("default") and target["default"] != c["default"]:
                target["published_default"] = target["default"]
                if target.get("unit"):
                    target["published_unit"] = target["unit"]
                stats["range_differs_from_published"] += 1
            target["default"] = c["default"]
            if c.get("unit"):
                target["unit"] = c["unit"]
        elif c.get("unit") and not target.get("unit"):
            target["unit"] = c["unit"]
        if "by_sex" in c:
            target["by_sex"] = c["by_sex"]
        target["source"] = "labqar+curated"
        stats["merged"] += 1
    return generated, dict(stats)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="path to the LabQAR supplementary xlsx")
    ap.add_argument("-o", "--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    rows = load_rows(Path(args.xlsx))
    analytes, stats, collisions = build(rows)
    analytes, mstats = merge_curated(analytes, CURATED)

    doc = {
        "version": "labqar-550-v1",
        "source": {
            "dataset": Path(args.xlsx).name,
            "rows": len(rows),
            "note": "Generated by data/labqar/build_reference_table.py — do not hand-edit; "
                    "re-run the converter. PENDING CLINICIAN REVIEW: ranges are published "
                    "Western reference intervals; Indian-specific analytes must be reviewed "
                    "before clinical trust (ARCHITECTURE.md section 6[5]).",
            "rules": [
                "only 'Normal' type rows used as reference intervals",
                "cycle-phase/posture/smoking-conditioned rows excluded from defaults",
                "curated POC critical thresholds, directions and aliases take precedence",
            ],
        },
        "analytes": analytes,
    }
    out = Path(args.out)
    out.write_text(
        "# GENERATED FILE — see data/labqar/build_reference_table.py\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")

    print(f"wrote {out}")
    print(f"  analytes emitted : {len(analytes)}")
    for k, v in sorted({**stats, **mstats}.items()):
        print(f"  {k:34s} {v}")
    if collisions:
        print(f"  ambiguous aliases dropped ({len(collisions)}):")
        for key, owners in sorted(collisions.items())[:15]:
            print(_console_safe(f"    {key!r} claimed by {owners}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
