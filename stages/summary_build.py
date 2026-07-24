"""Prompt construction + response parsing for Summary Generation (Phase 4).

The prompt embeds the OCR fields as a machine-readable JSON block so (a) real
LLMs get grounded, explicit input and (b) the stub engine can recover the exact
fields to build a faithful summary without a model. The model is instructed to
return ONLY JSON matching SummarySchema and to never invent values.
"""

from __future__ import annotations

import json
import re

from core.context import OCRField

FIELDS_OPEN = "<OCR_FIELDS_JSON>"
FIELDS_CLOSE = "</OCR_FIELDS_JSON>"

SYSTEM_PROMPT = (
    "You are a medical record structuring assistant for a point-of-care kiosk. "
    "You DO NOT diagnose. You ONLY reorganize the provided OCR fields into a "
    "structured summary. CRITICAL RULES:\n"
    "1. Every value you output MUST come verbatim from the provided OCR fields. "
    "Never invent, infer, or 'correct' a medical value.\n"
    "2. If something is not present in the OCR fields, add its name to "
    "'unknowns' — do not guess.\n"
    "2b. The fields are grouped by report page. Work through EVERY page group "
    "and include the findings and medications from ALL of them. Do not stop "
    "after the first page. A session often holds several reports, and a value "
    "you skip never reaches the doctor.\n"
    "3. Set each finding's 'source_field' to JUST the field's \"name\" value — "
    "a short plain string like \"Blood Urea\". It must be a single JSON string, "
    "never an array, never JSON, never a page reference, and never longer than "
    "the name itself. If two fields apply, put both names in that one string "
    "separated by a comma.\n"
    "4. 'narrative_en' MUST be 2-4 complete English sentences of flowing prose "
    "that a doctor can read aloud. Open by saying who issued the report and "
    "when, then describe the findings in sentences.\n"
    "   - Write sentences, NOT a list. "
    "'Hemoglobin: 9.5 g/dL, WBC: 11200 /cumm' is WRONG — it is a list with "
    "commas. 'Hemoglobin is 9.5 g/dL, which is below the printed reference "
    "range of 13.0-17.0 g/dL.' is RIGHT.\n"
    "   - Never use the 'Label: value' pattern. Every sentence needs a verb.\n"
    "   - You MAY state that a value sits above or below the reference range "
    "PRINTED ON THE REPORT ITSELF, because that is a factual comparison of two "
    "given numbers.\n"
    "   - You MUST NOT name, suggest, or imply any disease, condition or "
    "diagnosis, and MUST NOT give advice, treatment or prognosis. Never write "
    "phrases like 'suggests anemia', 'consistent with diabetes', 'indicates "
    "infection', or 'should consult'. Describe the numbers only.\n"
    "   - Mention every lab finding you listed, and the medications if any.\n"
    "   - ATTRIBUTION: each OCR field carries a 'page' number. A value belongs "
    "to the facility, doctor and date printed on the SAME page. Use that to "
    "attribute correctly when the session holds more than one report — never "
    "credit a value to a facility or doctor from a different page. If a page "
    "has no facility or doctor of its own, do not invent one: say the source is "
    "not stated for that value.\n"
    "5. Use no numbers anywhere in the narrative except ones present in the OCR "
    "fields.\n"
    "Return ONLY a JSON object matching the requested schema — no prose, no code fences."
)

SCHEMA_HINT = {
    "patient_language": "hi",
    "facility": "string or null",
    "doctor": "string or null",
    "report_dates": ["string"],
    "lab_findings": [
        {"analyte": "string", "value": "string", "unit": "string or null",
         "ref_range": "string or null", "source_field": "OCR field name"}
    ],
    "medications": [{"name": "string", "source_field": "OCR field name"}],
    "narrative_en": ("2-4 sentences of flowing English prose describing the report and its "
                     "findings. Sentences with verbs, never a 'Label: value' list. "
                     "No diagnosis, no advice."),
    "unknowns": ["string"],
}


# One worked example for BASE (non-instruct) models like Sarvam-1: base models
# can't follow instructions zero-shot, so a fair eval shows them the task once.
# Instruct models never see this — their chat template carries the instruction.
_FEW_SHOT_INPUT = [
    {"name": "Facility", "value": "City Diagnostic Centre", "unit": None, "low_confidence": False},
    {"name": "Report Date", "value": "12/03/2026", "unit": None, "low_confidence": False},
    {"name": "Hemoglobin", "value": "10.2", "unit": "g/dL", "low_confidence": False},
    {"name": "Hemoglobin ref-range", "value": "13.0-17.0", "unit": "g/dL", "low_confidence": False},
    {"name": "drug", "value": "Tab Ferrous Sulphate 200mg", "unit": None, "low_confidence": False},
]

# The narrative here is the STYLE TARGET: full sentences, opens with who/when,
# compares to the report's own printed range, names the medication, and stops
# short of any clinical conclusion. Instruct models never see this example, so
# rule 4 in SYSTEM_PROMPT must carry the same instruction in words.
_FEW_SHOT_OUTPUT = {
    "patient_language": "hi",
    "facility": "City Diagnostic Centre",
    "doctor": None,
    "report_dates": ["12/03/2026"],
    "lab_findings": [
        {"analyte": "Hemoglobin", "value": "10.2", "unit": "g/dL",
         "ref_range": "13.0-17.0", "source_field": "Hemoglobin"}
    ],
    "medications": [{"name": "Tab Ferrous Sulphate 200mg", "source_field": "drug"}],
    "narrative_en": (
        "This report was issued by City Diagnostic Centre on 12/03/2026. "
        "Hemoglobin is recorded as 10.2 g/dL, which falls below the reference "
        "range of 13.0-17.0 g/dL printed on the report. "
        "The report also lists Tab Ferrous Sulphate 200mg as a current medication. "
        "No referring doctor is named on the report."
    ),
    "unknowns": ["doctor"],
}

FEW_SHOT_EXAMPLE = (
    "Example.\n"
    f"OCR fields:\n{FIELDS_OPEN}\n{json.dumps(_FEW_SHOT_INPUT, ensure_ascii=False)}\n{FIELDS_CLOSE}\n"
    f"JSON:\n{json.dumps(_FEW_SHOT_OUTPUT, ensure_ascii=False)}"
)


def fields_to_json(ocr_fields: list[OCRField]) -> str:
    """Serialize fields for the prompt, including page provenance when present.

    ``page`` lets the model tie a value to the facility/doctor/date printed on
    the SAME page. Without it the list is flat and attribution is guesswork —
    which is exactly how one lab's results got credited to another lab's doctor.
    """
    # Fold "<X> ref-range" rows into X itself. Two rows per analyte doubled the
    # prompt AND made the model match them up by name; one row is smaller and
    # unambiguous. On a 16-page report the verbose two-row form ran ~14k chars,
    # and a 3B model given that much structured JSON stopped transforming and
    # started ECHOING the input back until it hit the token cap -> empty summary.
    ranges: dict[str, OCRField] = {}
    for f in ocr_fields:
        if f.name.endswith(" ref-range"):
            key = (f.name[: -len(" ref-range")], f.page_index)
            ranges[str(key)] = f

    def row(f: OCRField) -> dict:
        r: dict = {"name": f.name, "value": f.value}
        if f.unit:
            r["unit"] = f.unit
        rng = ranges.get(str((f.name, f.page_index)))
        if rng is not None:
            r["ref_range"] = rng.value
        if f.low_confidence:
            r["low_confidence"] = True
        return r

    ocr_fields = [f for f in ocr_fields if not f.name.endswith(" ref-range")]

    # When provenance exists, GROUP by page instead of emitting a flat list with
    # a page attribute. A flat list left a 3B model free to mix pages — it kept
    # crediting one lab's results to another lab's doctor. Nesting makes the
    # boundary structural rather than something the model has to remember.
    if any(f.page_index is not None for f in ocr_fields):
        by_page: dict[int, list[OCRField]] = {}
        for f in ocr_fields:
            by_page.setdefault(f.page_index if f.page_index is not None else -1, []).append(f)
        pages = [
            {"page": idx, "fields": [row(f) for f in flds]}
            for idx, flds in sorted(by_page.items())
        ]
        return json.dumps(pages, ensure_ascii=False)

    return json.dumps([row(f) for f in ocr_fields], ensure_ascii=False)


def build_prompt(ocr_fields: list[OCRField], patient_language: str = "hi") -> tuple[str, str]:
    """Return (system_prompt, user_prompt)."""
    user = (
        f"patient_language: {patient_language}\n\n"
        f"Schema to fill (types are hints):\n{json.dumps(SCHEMA_HINT, ensure_ascii=False)}\n\n"
        f"OCR fields (the ONLY source of truth), grouped by report page — a "
        f"value belongs to the facility/doctor/date listed in ITS OWN page group:\n"
        f"{FIELDS_OPEN}\n{fields_to_json(ocr_fields)}\n{FIELDS_CLOSE}\n\n"
        # Restated AFTER the data: with a long field block the instruction at the
        # top falls out of the model's attention and it continues the JSON it can
        # see rather than the schema it was asked for.
        f"Now output ONLY the summary JSON object matching the schema above. "
        f"Do NOT repeat, echo or reformat the OCR field list — transform it into "
        f"the schema. Start your reply with '{{' and output nothing else."
    )
    return SYSTEM_PROMPT, user


def extract_fields_block(prompt: str) -> list[dict]:
    """Recover the embedded OCR fields JSON from a prompt (used by the stub).

    Always returns a FLAT list of field rows, whichever shape fields_to_json
    emitted. That function has two: a flat list when no field carries page
    provenance, and a page-grouped list of ``{"page": i, "fields": [...]}``
    wrappers when one does. The caller only ever wants field rows, and returning
    the wrappers unflattened crashed the stub on ``f["value"]`` — every real
    multi-page OCR session hits the grouped shape, so the documented no-deps
    fallback died at stage [4] on exactly the input it exists to handle.
    """
    m = re.search(re.escape(FIELDS_OPEN) + r"(.*?)" + re.escape(FIELDS_CLOSE), prompt, re.DOTALL)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    rows: list[dict] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("fields"), list):        # page-grouped wrapper
            rows.extend(f for f in entry["fields"] if isinstance(f, dict))
        else:                                            # already a field row
            rows.append(entry)
    return rows


_DEVANAGARI = ("ऀ", "ॿ")
# Other Indic script blocks (Bengali .. Malayalam, incl. Gujarati) — a Hindi
# narrative must not be written in any of these.
_OTHER_INDIC = ("ঀ", "ൿ")


def wrong_script_for_hindi(text: str) -> bool:
    """True if ``text`` is written in a non-Devanagari script.

    Latin-only text (analyte names, numbers) is tolerated alongside Devanagari,
    but a narrative dominated by another Indic script — or containing no
    Devanagari at all while having letters — is wrong for Hindi.
    """
    if not text.strip():
        return False
    dev = sum(1 for c in text if _DEVANAGARI[0] <= c <= _DEVANAGARI[1])
    other = sum(1 for c in text if _OTHER_INDIC[0] <= c <= _OTHER_INDIC[1])
    has_alpha = any(c.isalpha() for c in text)
    return other > dev or (dev == 0 and has_alpha)


def parse_summary(text: str) -> dict:
    """Extract the first JSON object from a model response (tolerant of fences).

    If the object is truncated (model hit max_tokens mid-generation — e.g. a
    repetition loop), salvage the longest valid prefix: cut back to a complete
    element and close the open brackets, so the good findings survive.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # Find the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1:
        raise ValueError("No JSON object found in model response.")
    if end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Models intermittently emit a PYTHON dict literal (single quotes,
        # True/False/None) instead of JSON. The content is correct and complete;
        # only the quoting convention differs, and discarding it threw away a
        # perfectly good summary — measured on a real report, run to run.
        parsed = _parse_python_literal(candidate)
        if parsed is not None:
            return parsed
    salvaged = _repair_truncated_json(text[start:])
    if salvaged is None:
        raise ValueError("No JSON object found in model response.")
    salvaged.setdefault("unknowns", []).append(
        "parse_warning: model output was truncated — recovered partial JSON")
    return salvaged


def _parse_python_literal(candidate: str) -> dict | None:
    """Parse a Python dict literal (single quotes / True / None) as a dict.

    ``ast.literal_eval`` only evaluates literals — no calls, no names, no
    attribute access — so it is safe on untrusted model output in a way ``eval``
    would not be.
    """
    import ast

    try:
        value = ast.literal_eval(candidate)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _needed_closers(candidate: str) -> str | None:
    """Closing brackets to balance ``candidate``, or None if malformed."""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in candidate:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack or stack.pop() != ("{" if ch == "}" else "["):
                return None
    if in_string:
        return None
    return "".join("}" if b == "{" else "]" for b in reversed(stack))


def _repair_truncated_json(text: str) -> dict | None:
    """Best-effort recovery of a truncated JSON object.

    Repeatedly cut back to the last complete ``}`` (a finished element),
    balance the remaining open brackets, and try to parse.
    """
    while True:
        end = text.rfind("}")
        if end <= 0:
            return None
        candidate = text[:end + 1]
        closers = _needed_closers(candidate)
        if closers is not None:
            try:
                parsed = json.loads(candidate + closers)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        text = text[:end]
