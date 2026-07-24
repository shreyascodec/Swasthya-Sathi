"""Structured schema for the स्वास्थ्य साथी रिपोर्ट summary draft (Phase 4).

The LLM fills THIS schema from OCR output — it does not free-chat. Every medical
value carries a ``source_field`` that must trace back to an OCR field name;
anything the model cannot ground is listed in ``unknowns`` rather than invented
(faithfulness invariant). The summary is an ENGLISH-ONLY clinical document:
the patient-language surface (Hindi etc.) is produced at the voice boundary
(stages/s7_voice.py), never stored here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


#: A field NAME is short. Anything longer is the model dumping input back.
_MAX_SOURCE_FIELD_CHARS = 120


def _coerce_source_field(v):
    """Normalize source_field to the short comma-separated string the schema declares.

    Two real failure modes seen on live reports:
      * a JSON ARRAY of names — rejecting it failed validation for the WHOLE
        summary and silently emptied it (narrative, findings and all);
      * an echo of the entire input JSON stuffed into the field, which ate the
        token budget so ``narrative_en`` was truncated away entirely.
    """
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x).strip() for x in v if str(x).strip()) or "unknown"
    if isinstance(v, str) and len(v) > _MAX_SOURCE_FIELD_CHARS:
        # Keep the leading name if one is recoverable, else mark it unusable.
        head = v.split(",")[0].split('"')[0].strip()
        return (head[:_MAX_SOURCE_FIELD_CHARS] or "unknown")
    return v


class LabFinding(BaseModel):
    analyte: str
    value: str
    unit: str | None = None
    ref_range: str | None = None
    source_field: str = "unknown"   # OCR field name(s) this traces to; "unknown" if not

    _norm_source = field_validator("source_field", mode="before")(_coerce_source_field)


class Medication(BaseModel):
    name: str
    source_field: str = "unknown"

    _norm_source = field_validator("source_field", mode="before")(_coerce_source_field)


class SummarySchema(BaseModel):
    """The structured content stored in SummaryDoc.content."""

    patient_language: str = "hi"
    facility: str | None = None
    doctor: str | None = None
    report_dates: list[str] = Field(default_factory=list)
    lab_findings: list[LabFinding] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    narrative_en: str = ""
    unknowns: list[str] = Field(default_factory=list)

    def all_values(self) -> list[tuple[str, str]]:
        """(label, value) pairs that must trace to OCR — for faithfulness."""
        out: list[tuple[str, str]] = []
        for f in self.lab_findings:
            out.append((f.analyte, f.value))
            if f.ref_range:
                out.append((f"{f.analyte} ref-range", f.ref_range))
        return out
