"""Stub LLM — deterministic, always-faithful summary builder (no model).

It recovers the OCR fields embedded in the prompt and assembles a SummarySchema
directly from them, so it never hallucinates. This lets the whole Phase-4
pipeline + faithfulness gate + bake-off harness run and be tested with no GPU
and no model download. Swap to a real model by setting llm.primary.impl.

For testing the faithfulness checker, spec ``inject_hallucination: true`` makes
the stub add one ungrounded value on purpose.
"""

from __future__ import annotations

import json
import re

from core.model_manager import register_adapter
from models.llm_base import LLMAdapterBase
from stages.summary_build import extract_fields_block
from stages.summary_schema import LabFinding, Medication, SummarySchema

_NON_LAB = {"date", "doctor", "facility", "drug"}


class StubLLMAdapter(LLMAdapterBase):
    default_vram_mb = 0

    def _build(self):
        return {"stub": True}

    def _generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        fields = extract_fields_block(user)
        lang_m = re.search(r"patient_language:\s*(\w+)", user)
        lang = lang_m.group(1) if lang_m else "hi"

        # A row without "value" is not a measurement. Skipping is what the
        # fallback should do; indexing f["value"] blind is what made a bad row
        # take the whole pipeline down instead of degrading.
        by_name = [(f.get("name", ""), f) for f in fields if f.get("value") is not None]
        dates = [f["value"] for n, f in by_name if n.lower() == "date"]
        facility = next((f["value"] for n, f in by_name if n.lower() == "facility"), None)
        doctor = next((f["value"] for n, f in by_name if n.lower() == "doctor"), None)
        meds = [Medication(name=f["value"], source_field="drug")
                for n, f in by_name if n.lower() == "drug"]

        ref_ranges = {n[: -len(" ref-range")].lower(): f["value"]
                      for n, f in by_name if n.lower().endswith("ref-range")}

        findings: list[LabFinding] = []
        for n, f in by_name:
            nl = n.lower()
            if nl in _NON_LAB or nl.endswith("ref-range"):
                continue
            findings.append(LabFinding(
                analyte=n, value=f["value"], unit=f.get("unit"),
                ref_range=ref_ranges.get(nl), source_field=n,
            ))

        summary = SummarySchema(
            patient_language=lang,
            facility=facility,
            doctor=doctor,
            report_dates=dates,
            lab_findings=findings,
            medications=meds,
            narrative_en=self._narrative_en(facility, findings),
            unknowns=[],
        )

        if self.spec.get("inject_hallucination"):
            summary.lab_findings.append(
                LabFinding(analyte="Cholesterol", value="999", unit="mg/dL",
                           source_field="unknown")
            )

        return json.dumps(summary.model_dump(), ensure_ascii=False)

    @staticmethod
    def _narrative_en(facility: str | None, findings: list[LabFinding]) -> str:
        parts = []
        if facility:
            parts.append(f"Report from {facility}.")
        for f in findings:
            parts.append(f"{f.analyte}: {f.value} {f.unit or ''}".strip() + ".")
        return " ".join(parts)

register_adapter("stub_llm", lambda logical_name, spec, env: StubLLMAdapter(logical_name, spec, env))
