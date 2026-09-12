"""[5] Interpretation — rule-based Low/Normal/High/critical vs LabQAR.

Reads the faithful Phase-4 summary findings, looks each value up against the
LabQAR reference table (sex-aware when the session carries it; else the report's
own printed range), and writes a status per analyte into ``ctx.interpretations``.
High-priority/critical flags are surfaced back into the summary content so the
doctor sees them first.

Pure lookup + comparison — NO model, NO diagnosis, NO autonomous escalation
(product invariant). Values it cannot compare cleanly are left ``unknown`` and
flagged for review rather than guessed.

Tested/won/open: range parsing, table + printed-range fallback, low/normal/high/
critical, unit-mismatch review, high-priority surfacing, no-diagnosis schema, and
standalone harness run verified (tests/test_phase5.py). Open: swap in the real
550-row LabQAR xlsx; age/gender/specimen context once the intake captures it.
"""

from __future__ import annotations

import re

from core.context import LabFlag, SessionContext
from core.stage import Stage
from stages.interpret_rules import (
    Interpretation,
    load_reference_table,
    interpret_value,
)


class InterpretStage(Stage):
    name = "interpret"
    order = 5
    description = "Rule-based Low/Normal/High/critical flags vs LabQAR (no model)."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._table = None

    def _cfg(self) -> dict:
        return self.config.stage_cfg("interpret")

    def load(self) -> None:
        if self._table is None:
            cfg = self._cfg()
            path = cfg.get("reference_path")
            self._table = load_reference_table(path) if path else load_reference_table()

    def run(self, ctx: SessionContext) -> SessionContext:
        if self._table is None:
            self.load()

        cfg = self._cfg()
        high_priority = tuple(cfg.get("high_priority_statuses", ["critical"]))
        sex = getattr(ctx, "patient_sex", None)  # optional; absent in POC context

        findings = self._findings(ctx)
        recovered = self._recovered_analytes(ctx, findings)
        flags: list[LabFlag] = []
        interps: list[Interpretation] = []
        for f in findings:
            interp = interpret_value(
                analyte=f.get("analyte", ""),
                value=str(f.get("value", "")),
                unit=f.get("unit"),
                printed_ref=f.get("ref_range"),
                table=self._table,
                sex=sex,
                high_priority_statuses=high_priority,
            )
            interps.append(interp)
            flags.append(LabFlag(
                analyte=interp.analyte,
                value=interp.value,
                unit=interp.unit,
                ref_range=interp.ref_range,
                status=interp.status,          # STATUS ONLY — never a diagnosis
                high_priority=interp.high_priority,
            ))

        ctx.interpretations = flags
        self._surface_high_priority(ctx, flags)

        # MCH mode: stratify the maternal risk tier from the per-parameter
        # statuses (vitals only here; the danger-sign answers are folded in at
        # the report stage, once the Q&A has run). Config-selected so the lab
        # path is untouched.
        if cfg.get("mode") == "maternal" and ctx.summary is not None:
            from stages.maternal_risk import assess_maternal_risk
            ctx.summary.content["maternal_risk"] = assess_maternal_risk(findings, flags)

        contradictions = self._narrative_contradictions(ctx, flags)

        counts = {s: sum(1 for x in flags if x.status == s)
                  for s in ("low", "normal", "high", "critical", "unknown")}
        ctx.log(
            "stage.interpret.done",
            detail=(f"table={self._table.version} flagged={len(flags)} "
                    f"counts={counts} "
                    f"needs_review={sum(1 for i in interps if i.needs_review)} "
                    f"recovered_from_ocr={len(recovered)}"
                    + (f" ({','.join(recovered)})" if recovered else "")
                    + f" narrative_contradictions={len(contradictions)}"
                    + (f" ({'; '.join(contradictions)})" if contradictions else "")),
        )
        return ctx

    @staticmethod
    def _analyte_pattern(analyte: str) -> str:
        """Match the analyte as prose writes it: "Platelets" must find "Platelet
        count", and "WBC" must find "WBC count". Singular/plural tolerant."""
        stem = re.escape(str(analyte).rstrip("sS"))
        return rf"\b{stem}s?\b(?:\s+(?:count|level|percentage|value))?"

    #: words an LLM narrative uses to assert a range verdict
    _SAYS_NORMAL = re.compile(r"\bwithin\b|\bnormal range\b|\bwithin normal\b", re.I)
    _SAYS_HIGH = re.compile(r"\babove\b|\bexceed\w*\b|\bhigher\b|\belevated\b", re.I)
    _SAYS_LOW = re.compile(r"\bbelow\b|\blower\b|\breduced\b|\bless than\b", re.I)

    def _narrative_contradictions(
        self, ctx: SessionContext, flags: list[LabFlag]
    ) -> list[str]:
        """Flag narrative claims that contradict the deterministic statuses.

        The narrative is written by an LLM BEFORE this stage computes the real
        verdict, and LLMs get numeric comparisons wrong: MedGemma-4B wrote
        "WBC 11200 /cumm, within the normal range of 4000-11000" — 11200 exceeds
        11000 — and called a below-range platelet count normal, in a run where the
        rules here correctly flagged both. A narrative that says "normal" while
        the flags say "high" is worse than no narrative, so mismatches are
        recorded for review rather than left for a clinician to notice.

        Rules win: ctx.interpretations is the authority, this only reports.
        """
        if ctx.summary is None:
            return []
        narrative = str(ctx.summary.content.get("narrative_en") or "")
        if not narrative:
            return []

        out: list[str] = []
        for flag in flags:
            if flag.status not in ("low", "high", "critical"):
                continue
            for m in re.finditer(self._analyte_pattern(flag.analyte), narrative, re.I):
                # Clause about this analyte: to the next ';' or sentence-ending
                # '.'. Splitting on a bare '.' would cut at the decimal point in
                # "9.5" and hide the verdict that follows it.
                tail = narrative[m.end():]
                clause = re.split(r";|\.(?=\s|$)", tail, maxsplit=1)[0]

                # Judge on the FIRST verdict word after the analyte only. A
                # sentence can chain analytes ("Hemoglobin ... below ... and WBC
                # ... above ..."), and scanning the whole clause read the next
                # analyte's verdict as this one's — a false contradiction.
                first = None
                for kind, pat in (("normal", self._SAYS_NORMAL),
                                  ("high", self._SAYS_HIGH),
                                  ("low", self._SAYS_LOW)):
                    hit = pat.search(clause)
                    if hit and (first is None or hit.start() < first[1]):
                        first = (kind, hit.start())
                if first is None:
                    break
                said = first[0]
                if said == "normal":
                    out.append(f"{flag.analyte} is {flag.status} but narrative says normal")
                elif (flag.status == "low" and said == "high") or \
                     (flag.status in ("high", "critical") and said == "low"):
                    out.append(f"{flag.analyte} is {flag.status} but narrative says the opposite")
                break
        if out:
            ctx.summary.content["narrative_review"] = out
        return out

    def _recovered_analytes(self, ctx: SessionContext, findings: list[dict]) -> list[str]:
        """Analytes OCR read that the summary LLM omitted — recovered by the union.

        A non-empty list means the summary is incomplete; it is a completeness
        signal for the bench and a review cue for the operator UI.
        """
        if not (ctx.summary and ctx.summary.content.get("lab_findings")):
            return []
        in_summary = {self._analyte_key(f.get("analyte", ""))
                      for f in ctx.summary.content["lab_findings"]}
        return [str(f.get("analyte", "")) for f in findings
                if self._analyte_key(f.get("analyte", "")) not in in_summary]

    def _findings(self, ctx: SessionContext) -> list[dict]:
        """UNION of the Phase-4 summary findings and the raw OCR values.

        The summary is written by an LLM, and an LLM can silently OMIT a value it
        was given: Qwen2.5-3B dropped a diabetic-range HbA1c (7.8%) from a report
        where OCR had read it at 0.956 confidence, so it never reached the
        doctor's flags and the intake Q&A then asked the patient for a test that
        was printed on the page. The faithfulness gate cannot catch this — it
        checks that nothing was INVENTED, never that nothing was LOST.

        So OCR values are the floor: every analyte OCR read is interpreted, and
        the summary's entry wins on overlap (it carries the model's ref_range /
        source_field). No model omission can remove a value from the flags.
        """
        summary_findings = []
        if ctx.summary and ctx.summary.content.get("lab_findings"):
            summary_findings = list(ctx.summary.content["lab_findings"])

        merged = list(summary_findings)
        seen = {self._analyte_key(f.get("analyte", "")) for f in summary_findings}
        for f in self._ocr_findings(ctx):
            key = self._analyte_key(f["analyte"])
            if key and key not in seen:
                seen.add(key)
                merged.append(f)
        return merged

    #: British/American and common report spelling variants. Without these the
    #: union merge double-counts: a real 16-page session produced 65 flags for 59
    #: values because the model wrote "Haemoglobin" where OCR read "Hemoglobin".
    _SPELLING = (
        ("haem", "hem"), ("oe", "e"), ("sulphate", "sulfate"),
        ("leucocyte", "leukocyte"), ("gray", "grey"),
    )

    @classmethod
    def _analyte_key(cls, name: str) -> str:
        """Match analyte names across sources despite spacing, case, punctuation
        and spelling variants, so the same analyte merges instead of duplicating."""
        key = "".join(ch for ch in str(name).lower() if ch.isalnum())
        for src, dst in cls._SPELLING:
            key = key.replace(src, dst)
        return key

    #: OCR field names that are metadata, never analytes.
    _NON_ANALYTE = {"facility", "doctor", "date", "page", "drug"}

    def _ocr_findings(self, ctx: SessionContext) -> list[dict]:
        """Reconstruct findings from OCR value fields + their ref-range partner."""
        if not ctx.ocr:
            return []
        refs = {f.name.replace(" ref-range", ""): f.value
                for f in ctx.ocr.fields if f.name.endswith("ref-range")}
        out = []
        for f in ctx.ocr.fields:
            if f.name.endswith("ref-range") or f.unit is None:
                continue
            if f.name.strip().lower() in self._NON_ANALYTE:
                continue
            out.append({"analyte": f.name, "value": f.value, "unit": f.unit,
                        "ref_range": refs.get(f.name)})
        return out

    def _surface_high_priority(self, ctx: SessionContext, flags: list[LabFlag]) -> None:
        """Write high-priority + abnormal flags into the summary for the doctor."""
        if ctx.summary is None:
            return
        abnormal = [f for f in flags if f.status in ("low", "high", "critical")]
        ctx.summary.content["abnormal_flags"] = [
            {"analyte": f.analyte, "value": f.value, "unit": f.unit,
             "status": f.status, "ref_range": f.ref_range}
            for f in abnormal
        ]
        ctx.summary.content["high_priority_flags"] = [
            {"analyte": f.analyte, "value": f.value, "status": f.status}
            for f in flags if f.high_priority
        ]
