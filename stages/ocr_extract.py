"""Structured field extraction from OCR output (deterministic, engine-agnostic).

Turns raw OCR text + tokens into typed OCRField rows: lab value + unit +
printed reference range, dates, drugs, doctor, facility. Per-field confidence is
derived from the source tokens; fields below the configured threshold are marked
``low_confidence`` so the UI can flag them for manual review (deck risk item:
"OCR fails on handwritten reports -> low-confidence fields flagged").

Pure and fully testable — no model, no engine dependency.
"""

from __future__ import annotations

import re

from core.context import OCRField
from models.ocr_base import OCRToken

# Common Indian lab-report units. Longer strings first so e.g. "mg/dL" wins over
# "g/dL" during alternation.
_UNITS = sorted(
    [
        "g/dL", "g/dl", "mg/dL", "mg/dl", "mg/L", "mmol/L", "µmol/L", "umol/L",
        "IU/L", "U/L", "mIU/L", "µIU/mL", "uIU/mL", "ng/mL", "ng/dL", "pg/mL",
        "pg", "fL", "fl", "cells/cumm", "/cumm", "million/cumm", "thousand/cumm",
        "lakhs/cumm", "mEq/L", "%",
        "mm2", "mm²", "mmHg", "kg", "Kg", "KG",
    ],
    key=len,
    reverse=True,
)
_UNIT_ALT = "|".join(re.escape(u) for u in _UNITS)
_NUM = r"\d+(?:\.\d+)?"

_VALUE_RE = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z0-9 ()./%-]{{1,39}}?)\s*[:=\-]?\s*"
    rf"(?P<value>{_NUM})\s*(?P<unit>{_UNIT_ALT})"
    rf"(?:\s*\(?\s*(?P<low>{_NUM})\s*[-\u2013]\s*(?P<high>{_NUM})\s*\)?)?"
)

# Unitless table row: "<LABEL> <value>" at end of line (many report tables print
# no unit — e.g. ophthalmic "CDR 0.42", "VDD 1.73"). End-anchoring keeps chart
# axis numbers and other mid-line noise out.
_KV_EOL_RE = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z0-9 ()./%-]{{1,39}}?)\s*[:=]?\s*(?P<value>{_NUM})\s*$"
)

# --- horizontal row: "<ANALYTE> <value> [unit] <low>-<high> [unit]" -----------
# The layout real Indian lab reports use when the whole row survives on ONE line:
#     Direct Bilirubin 0.10 mg/dIl 0-0.40 mg/dl
#     Transferin Saturation 12.45 20-50%
#     A/G Ratio 1.48 1.0-2.5
# _VALUE_RE cannot read these: it requires a RECOGNIZED unit straight after the
# value, so a unitless row ("A/G Ratio 1.48 1.0-2.5") or an OCR-corrupted unit
# ("mg/dIl") both fall through to _KV_EOL_RE — which is END-anchored and so
# returned the reference-range HIGH as the measurement. Measured on the real
# bench reports that produced: Direct Bilirubin=0.40 (true 0.10), Transferrin
# Saturation=50 (true 12.45, i.e. a LOW value reported as normal), A/G Ratio=2.5
# (true 1.48). Those are wrong VALUES, not just unresolved names.
#
# The unit slot is deliberately loose ([A-Za-z/µ%.]) rather than _UNIT_ALT so
# OCR mangling of the unit cannot cost us the row.
# Must START with a letter/%/µ/'/': a leading '.' let the pattern eat the decimal
# point and split "2.3" into value "2" + unit "." + range "3-3.5", so '.' stays
# excluded. '/' must be ALLOWED: counted units are printed slash-first ("/cumm",
# and _UNITS lists it), and excluding it cost the measurement outright. On
# "WBC 11200 /cumm 4000-11000" the unit could not match, so the label
# backtracked to swallow "WBC 11200 /cumm" and the range split into value "400"
# + range "0-11000" — inventing 400 and losing a genuinely high WBC of 11200.
# _HROW_RE runs first and sets had_unit_match, so it also suppressed _VALUE_RE,
# which parses that line correctly. "cells/cumm" worked only because it happens
# to start with a letter.
_UNIT_LOOSE = r"[A-Za-zµ%/][A-Za-zµ%/\.]{0,11}"
_HROW_RE = re.compile(
    rf"^(?P<label>[A-Za-z][A-Za-z0-9 ()./%,'-]{{1,48}}?)\s+"
    rf"(?P<value>{_NUM})\s*"
    rf"(?P<unit>{_UNIT_LOOSE})?\s*"
    rf"(?P<low>{_NUM})\s*[-–]\s*(?P<high>{_NUM})\s*"
    rf"(?P<unit2>{_UNIT_LOOSE})?\s*$"
)

# A line whose TAIL is a reference range ("... 2.3-3.5 g/dl", "... 2-3"). When
# such a line yields no value via _HROW_RE the honest answer is NO FIELD: the
# row either lost its measurement in OCR ("Globulin g/dl 2.3-3.5 g/dl" — the
# value is simply absent) or the range IS the finding ("EPITHELIAL CELLS 2-3").
# Letting _KV_EOL_RE fire here is what invented values out of range bounds.
_TRAILING_RANGE_RE = re.compile(
    rf"{_NUM}\s*[-–]\s*{_NUM}\s*(?:{_UNIT_LOOSE})?\s*$"
)

_DATE_RES = [
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"),
    re.compile(
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4}\b",
        re.IGNORECASE,
    ),
]

_DOCTOR_RE = re.compile(r"\bDr\.?\s+[A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3}")

# Blood pressure "sys/dia" behind an explicit BP label (MCH mode). Bounded 2-3
# digits each so it can't match dates or ratios.
_BP_RE = re.compile(
    r"(?:b\.?\s*p\.?|blood\s*pressure)\s*[:\-]?\s*(?P<sys>\d{2,3})\s*/\s*(?P<dia>\d{2,3})",
    re.IGNORECASE,
)

# --- vertical (one-cell-per-line) table layout --------------------------------
# Real Indian lab PDFs emit each table CELL on its own line, not a row per line:
#     Blood Urea / : / 33.65 / mg/dl / 0-48.0 mg/dl
# The single-line _VALUE_RE cannot see that, so on real reports it extracted ZERO
# lab values (measured on test1-3: 6 "fields", all header/range junk). This
# parser reconstructs those records.
_VERT_NUM_RE = re.compile(rf"^\s*(?P<value>[<>]?\s*{_NUM})\s*$")
_VERT_RANGE_RE = re.compile(
    # Optional label ("Normal :", "Desirable:") then low..high with '-', '–' or
    # the word 'To' — real reports print "Normal : 4.0 To 5.6 %" as often as
    # "0-48.0 mg/dl". Also tolerates one-sided "< 200" / "Up to 150".
    rf"^\s*(?:[A-Za-z][A-Za-z\s\.]{{0,20}}?\s*:\s*)?"
    rf"(?:(?P<low>{_NUM})\s*(?:[-–]|\s+To\s+)\s*(?P<high>{_NUM})"
    rf"|[<>]\s*{_NUM}|Up\s*to\s*{_NUM})"
    rf"\s*(?P<unit>[A-Za-zµ%/\.\s]*)$",
    re.IGNORECASE,
)

# Interpretive prose / diagnostic-criteria footnotes are not measurements. They
# are long sentences, and reading values out of them produced fields like
# "yrs of age) = 5.7 %" and "To = 5.6 %" on a real report.
_INTERPRETIVE_MARKERS = (
    "diagnosis of", "increased risk", "is an estimated", "recommend", "guideline",
    "according to", "interpretation", "note:", "comment", "please correlate",
    "clinically", "suggested", "criteria", "toddlers", "school age",
    "high risk", "low risk", "desirable", "borderline", "approximately",
    "values above", "values below", "optimal", "deficiency", "sufficiency",
    "insufficiency", "toxicity", "automated", "method", "principle",
)


def _looks_interpretive(line: str) -> bool:
    low = line.lower()
    if any(m in low for m in _INTERPRETIVE_MARKERS):
        return True
    # Table cells are short; guidance is prose. Long lines with several numbers
    # and sentence punctuation are footnotes, not rows.
    return len(line) > 80 and len(re.findall(_NUM, line)) >= 2
# A unit line: short, no digits beyond exponents, not a sentence.
_VERT_UNIT_RE = re.compile(r"^\s*[A-Za-zµ%/\.\s\d]{1,18}\s*$")
_VERT_ANALYTE_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 ()\.\,'/%+-]{1,48}\s*$")
#: lines that look like analytes but are table furniture, not measurements
_VERT_SKIP_LABELS = {
    "test", "result", "unit", "biological ref. range", "ref. range", "reference range",
    "sample type", "specimen", "method", "units", "value", "investigation",
    "parameter", "parameters", "normal range", "interpretation", "comment", "comments",
    "name", "age", "sex", "ref. by", "ref by", "cd id", "printed", "report released",
    "sample collection", "sample received", "patient name", "lab no", "lab no.",
}


def _is_vertical_analyte(line: str) -> bool:
    s = line.strip().rstrip(":").strip()
    if not s or len(s) < 2 or s.lower() in _VERT_SKIP_LABELS:
        return False
    if s.lower().startswith(("method", "specimen", "note", "sample type")):
        return False
    if not _VERT_ANALYTE_RE.match(s):
        return False
    letters = sum(c.isalpha() for c in s)
    if letters >= 2:
        return True
    # Short symbol analytes are real and clinically important — T3, T4, B12 were
    # all being dropped by a 2-letter minimum. Allow 1 letter + <=2 digits, which
    # still rejects accession codes like "M21295".
    return bool(re.fullmatch(r"[A-Za-z]\d{1,2}", s))


def extract_vertical_records(lines: list[str]) -> tuple[list[dict], set[int]]:
    """Find ``analyte / : / value / [unit] / [ref-range]`` records laid out one
    cell per line. Returns the records and the line indices they consumed."""
    out: list[dict] = []
    consumed: set[int] = set()
    i = 0
    while i < len(lines) - 2:
        label_raw = lines[i].strip()
        # The colon may sit on its own line, or be glued to the label.
        if lines[i + 1].strip() == ":":
            value_idx = i + 2
        elif label_raw.endswith(":"):
            value_idx = i + 1
        else:
            i += 1
            continue
        # A long analyte name can wrap onto its own line: "eGFR (CKD-EPI)" then
        # "(Calculated)". Re-join the parenthetical BEFORE the analyte test —
        # "(Calculated)" alone starts with '(' and would be rejected outright.
        start = i
        if label_raw.startswith("(") and i > 0:
            prev = lines[i - 1].strip()
            if prev and _is_vertical_analyte(prev) and (i - 1) not in consumed:
                label_raw = f"{prev} {label_raw}"
                start = i - 1

        if value_idx >= len(lines) or not _is_vertical_analyte(label_raw):
            i += 1
            continue
        m = _VERT_NUM_RE.match(lines[value_idx])
        if not m:                       # non-numeric cell (e.g. "Sample Type: SERUM")
            i += 1
            continue

        rec = {"analyte": label_raw.rstrip(":").strip(),
               "value": m.group("value").replace(" ", ""),
               "unit": None, "ref_range": None}
        used = set(range(start, value_idx + 1))
        nxt = value_idx + 1
        # Optional unit line, then optional reference-range line.
        if nxt < len(lines):
            cand = lines[nxt].strip()
            if (cand and not _VERT_RANGE_RE.match(cand) and _VERT_UNIT_RE.match(cand)
                    and not _VERT_NUM_RE.match(cand) and not _is_vertical_analyte_start(lines, nxt)):
                rec["unit"] = cand
                used.add(nxt)
                nxt += 1
        if nxt < len(lines):
            rm = _VERT_RANGE_RE.match(lines[nxt].strip())
            if rm and rm.group("low") and rm.group("high"):
                rec["ref_range"] = f"{rm.group('low')}-{rm.group('high')}"
                if not rec["unit"] and rm.group("unit"):
                    rec["unit"] = rm.group("unit").strip() or None
                used.add(nxt)
        out.append(rec)
        consumed |= used
        i = max(used) + 1
    return out, consumed


def _is_vertical_analyte_start(lines: list[str], idx: int) -> bool:
    """True if lines[idx] begins the NEXT record (so it is not this one's unit)."""
    return (idx + 1 < len(lines) and lines[idx + 1].strip() == ":"
            and _is_vertical_analyte(lines[idx]))
# Dose-form marker anywhere in the line, not just at line start: real reports
# write "Advice / Medication: Tab Metformin 500mg", so an ^-anchored pattern
# missed every prescription that carried a label prefix.
_DRUG_RE = re.compile(r"\b(?:Tab|Cap|Syr|Inj|Tablet|Capsule|Rx)\b[.:]?\s*(.+)$", re.IGNORECASE)
_FACILITY_KEYWORDS = (
    "hospital", "clinic", "diagnostic", "laboratory", "labs", "pathology",
    "medical centre", "medical center", "healthcare", "nursing home",
)


# OCR engines emit typographic and fullwidth look-alikes for ASCII punctuation.
# A single fullwidth colon cost a real lab value: PaddleOCR read
# "Serum Chlorides ： 103.7 mEq/L" and the ASCII-only pattern skipped the row.
_PUNCT_NORMALIZE = {
    "：": ":", "；": ";", "，": ",", "．": ".",
    "／": "/", "％": "%", "（": "(", "）": ")",
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", "‘": "'", "’": "'",
    "“": '"', "”": '"',
}
_PUNCT_RE = re.compile("|".join(re.escape(k) for k in _PUNCT_NORMALIZE))


def normalize_ocr_punctuation(text: str) -> str:
    """Fold fullwidth/typographic punctuation to ASCII so patterns match."""
    return _PUNCT_RE.sub(lambda m: _PUNCT_NORMALIZE[m.group(0)], text)


def _conf_for(needles: list[str], tokens: list[OCRToken], default: float) -> float:
    """Min confidence among tokens overlapping any needle; else ``default``."""
    confs: list[float] = []
    for tok in tokens:
        tl = tok.text.lower()
        for n in needles:
            nl = n.strip().lower()
            if nl and (nl in tl or tl in nl):
                confs.append(tok.confidence)
                break
    return min(confs) if confs else default


def extract_fields(
    text: str,
    tokens: list[OCRToken] | None = None,
    low_confidence_threshold: float = 0.80,
    page_index: int | None = None,
    page_id: str | None = None,
) -> list[OCRField]:
    """Extract typed fields from one page's text.

    ``page_index``/``page_id`` stamp provenance onto every field so downstream
    stages can tell which report a value came from (see OCRField.page_index).
    """
    tokens = tokens or []
    page_conf = (sum(t.confidence for t in tokens) / len(tokens)) if tokens else 1.0
    fields: list[OCRField] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, value: str, unit: str | None, needles: list[str]) -> None:
        key = (name.lower(), value.lower())
        if not value or key in seen:
            return
        seen.add(key)
        conf = _conf_for(needles, tokens, page_conf)
        fields.append(
            OCRField(
                name=name,
                value=value,
                unit=unit,
                confidence=round(conf, 3),
                low_confidence=conf < low_confidence_threshold,
                page_index=page_index,
                page_id=page_id,
            )
        )

    # Pass 1: vertical (one-cell-per-line) tables — the layout real lab PDFs use.
    raw_lines = normalize_ocr_punctuation(text).splitlines()
    vertical, consumed = extract_vertical_records(raw_lines)
    for rec in vertical:
        add(rec["analyte"], rec["value"], rec["unit"],
            [rec["analyte"], rec["value"]])
        if rec["ref_range"]:
            add(f"{rec['analyte']} ref-range", rec["ref_range"], rec["unit"],
                [rec["value"]])

    # Pass 2: single-line rows + metadata. Lines already claimed by pass 1 are
    # skipped so an isolated "0-48.0 mg/dl" is not re-read as its own value.
    for idx, raw_line in enumerate(raw_lines):
        if idx in consumed:
            continue
        line = raw_line.strip()
        if not line:
            continue

        # Lab value (+ unit, + printed reference range). Guidance prose is skipped
        # for VALUES only — doctor/facility/date/drug below still scan every line.
        interpretive = _looks_interpretive(line)

        had_unit_match = False

        # Horizontal row with a trailing reference range, parsed FIRST so the
        # range bounds can never be read as the measurement (see _HROW_RE).
        hm = None if interpretive else _HROW_RE.match(line)
        if hm:
            label = hm.group("label").strip(" :.-")
            letters = sum(c.isalpha() for c in label)
            if len(label) >= 2 and letters >= 2 and label.lower() not in _VERT_SKIP_LABELS:
                unit = hm.group("unit") or hm.group("unit2")
                add(label, hm.group("value"), unit, [label, hm.group("value")])
                add(f"{label} ref-range",
                    f"{hm.group('low')}-{hm.group('high')}", unit,
                    [hm.group("low"), hm.group("high")])
                had_unit_match = True

        # Where the line TAIL is a reference range, no value may be read out of
        # that span. _VALUE_RE is not anchored, so on
        # "Direct Bilirubin 0.10 mg/dIl 0-0.40 mg/dl" it happily matched the
        # trailing "0.40 mg/dl" and reported the range's high bound as the
        # measurement. A legitimate value always precedes the range
        # ("Hemoglobin 13.5 g/dL (13.0-17.0)"), so position is the clean test.
        tail = _TRAILING_RANGE_RE.search(line)
        tail_start = tail.start() if tail else len(line)

        for m in ([] if (interpretive or had_unit_match) else _VALUE_RE.finditer(line)):
            label = m.group("label").strip(" :.-")
            value = m.group("value")
            unit = m.group("unit")
            if len(label) < 2 or m.start("value") >= tail_start:
                continue
            had_unit_match = True
            add(label, value, unit, [label, value])
            if m.group("low") and m.group("high"):
                add(f"{label} ref-range", f"{m.group('low')}-{m.group('high')}", unit, [value])

        # Unitless table row ("LABEL value" at end of line). Skipped when the
        # line already yielded a unit-ful value (avoids re-reading "2.50 mm2"
        # as label "... mm" value "2"), when the line TAIL is a reference range
        # (the value would be a range bound), and for ID-like zero-padded values.
        kv = (None if (had_unit_match or interpretive or tail)
              else _KV_EOL_RE.search(line))
        if kv:
            label = kv.group("label").strip(" :.-")
            value = kv.group("value")
            id_like = re.fullmatch(r"0\d+", value) is not None
            # Report headers are alphanumeric IDs, not measurements: "M21295
            # 220526" was being extracted as analyte "M21295" = 220526. Require a
            # word-like label (3+ letters, not a letter+digits accession code).
            code_like = re.fullmatch(r"[A-Za-z]{1,3}\d+", label) is not None
            letters = sum(c.isalpha() for c in label)
            # A label ending in a lone letter is a split compound name, not an
            # analyte: "Vitamin - B" / "12" and "VITAMIN D" / "3" were being read
            # as measurements on a real report.
            last = label.split()[-1] if label.split() else ""
            dangling_initial = len(last) == 1 and last.isalpha()
            if (len(label) >= 2 and letters >= 3 and not id_like and not code_like
                    and not dangling_initial
                    and label.lower() not in _VERT_SKIP_LABELS):
                add(label, value, None, [label, value])

        # Doctor
        for dm in _DOCTOR_RE.finditer(line):
            add("doctor", dm.group(0).strip(), None, [dm.group(0)])

        # Drug — record from the dose-form marker onward ("Tab Metformin 500mg"),
        # not the whole line, so a label prefix doesn't end up in the value.
        drug_m = _DRUG_RE.search(line)
        if drug_m:
            add("drug", drug_m.group(0).strip(), None, [drug_m.group(0)])

        # Facility. Real names are short headings; a keyword like "diagnostic"
        # also appears mid-sentence in clinical footnotes ("...is not the
        # telltale diagnostic sign of any one condition"), so require a
        # heading-shaped line rather than prose.
        low = line.lower()
        if (any(k in low for k in _FACILITY_KEYWORDS)
                and len(line) <= 60 and not interpretive
                and not re.search(r"\.\s+[A-Za-z]", line)):
            add("facility", line, None, [line])

    # Dates (scan whole text)
    for date_re in _DATE_RES:
        for dm in date_re.finditer(text):
            add("date", dm.group(0).strip(), None, [dm.group(0)])

    # Blood pressure "sys/dia" — a combined reading the numeric value patterns
    # above cannot capture (the '/' breaks value+unit). Needed for MCH mode
    # (pre-eclampsia). Additive and lab-safe: only fires on an explicit BP label.
    for bm in _BP_RE.finditer(normalize_ocr_punctuation(text)):
        sys, dia = bm.group("sys"), bm.group("dia")
        add("Blood Pressure", f"{sys}/{dia}", "mmHg", [bm.group(0)])

    return fields
