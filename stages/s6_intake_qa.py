"""[6] Intake Q&A — grounded questions (template + fill) + STT answers.

Deterministic triggers over the extracted data (interpreted lab flags, report
dates, medications) pick the top few question PATTERNS from the clinician-
reviewable bank; slots are filled from data only and rendered in the patient
language. The model is not required to produce question text (templates are
pre-translated), so a question can only ever come from the bank — the off-bank
guardrail is structural.

Answers are captured by STT (faster-whisper primary; stub for no-deps) and
attached to the summary. ``capture_answer`` is the seam the UI calls once the
patient has spoken.

Tested/won/open: trigger firing (gap references the real date), top-N selection,
off-bank guardrail, deterministic bilingual render, STT capture + attach via
stub, stub fallback. Open: real faster-whisper/IndicConformer runs; clinician
review of the bank; optional SLM re-phrasing behind the same guardrail.
"""

from __future__ import annotations

import re

from core.context import IntakeAnswer, IntakeQuestion, SessionContext
from core.stage import Stage
from stages.intake_qa_rules import (
    IntakeFacts,
    LabFact,
    load_question_bank,
    select,
    validate_from_bank,
)


class IntakeQAStage(Stage):
    name = "intake_qa"
    order = 6
    description = "Grounded intake questions (template+fill) + STT answers."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._bank = None
        self._stt = None

    def _cfg(self) -> dict:
        return self.config.stage_cfg("intake_qa")

    def load(self) -> None:
        if self._bank is None:
            cfg = self._cfg()
            path = cfg.get("bank_path")
            self._bank = load_question_bank(path) if path else load_question_bank()

    # -- facts assembly -------------------------------------------------------
    def _facts(self, ctx: SessionContext) -> IntakeFacts:
        labs: list[LabFact] = []
        present: set[str] = set()
        for fl in ctx.interpretations:
            labs.append(LabFact(analyte=fl.analyte, value=fl.value,
                                unit=fl.unit, status=fl.status))
            present.add(fl.analyte.strip().lower())

        content = ctx.summary.content if ctx.summary else {}
        # Present analytes also include anything the summary listed (even if the
        # interpreter left it 'unknown'), so 'missing_test' is judged on the full set.
        for f in content.get("lab_findings", []):
            present.add(str(f.get("analyte", "")).strip().lower())

        # Maternal-risk parameters (computed at stage 5) carry statuses the numeric
        # interpreter can't produce — a combined Blood Pressure ("150/100") and a
        # Urine Protein grade ("++"), which interpret leaves 'unknown'. Merge them:
        # for a NEW analyte, add it; for one already present as an 'unknown'
        # interpretation, let the definite maternal-risk status SUPERSEDE it, so a
        # high-BP / proteinuria follow-up can fire (it otherwise stays unknown and
        # never matches a lab_status trigger).
        by_key: dict[str, LabFact] = {}
        for lf in labs:
            by_key.setdefault(lf.analyte.strip().lower(), lf)
        mr = content.get("maternal_risk") or {}
        for prm in mr.get("parameters", []):
            name = str(prm.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            status = str(prm.get("status", "unknown"))
            value = str(prm.get("value", ""))
            existing = by_key.get(key)
            if existing is not None:
                if status != "unknown" and (existing.status or "unknown") in ("unknown", ""):
                    existing.status = status
                    if value:
                        existing.value = value
            else:
                lf = LabFact(analyte=name, value=value, unit=None, status=status)
                labs.append(lf)
                by_key[key] = lf
                present.add(key)

        dates = list(content.get("report_dates", []))
        meds = [m.get("name", "") for m in content.get("medications", []) if m.get("name")]

        return IntakeFacts(labs=labs, present_analytes=present,
                           report_dates=dates, medications=meds)

    def run(self, ctx: SessionContext) -> SessionContext:
        if self._bank is None:
            self.load()

        cfg = self._cfg()
        max_q = int(cfg.get("max_questions", 5))
        stale_months = int(cfg.get("stale_report_months", 6))
        max_grounded = int(cfg.get("max_grounded", 3))

        facts = self._facts(ctx)
        selected = select(self._bank, facts, max_questions=max_q,
                          stale_report_months=stale_months, max_grounded=max_grounded)

        questions: list[IntakeQuestion] = []
        used_ids: set[str] = set()
        for q in selected:
            # Guardrail: never surface a question whose pattern isn't in the bank.
            if not validate_from_bank(q.pattern_id, self._bank):
                continue
            rendered = q.text_hi if ctx.lang == "hi" else q.text_en
            # A generic pattern (cond_flagged_generic) can appear more than once —
            # one per flagged analyte — so the id must be unique per question, not
            # just per pattern, or two answers would collide on the same key.
            base = f"{ctx.session_id}:{q.pattern_id}"
            slug = re.sub(r"[^a-z0-9]+", "-", (q.slot or "").lower()).strip("-")
            qid = f"{base}:{slug}" if slug else base
            n = 2
            while qid in used_ids:
                qid = f"{base}:{slug}-{n}" if slug else f"{base}:{n}"
                n += 1
            used_ids.add(qid)
            questions.append(IntakeQuestion(
                id=qid,
                pattern_id=q.pattern_id,
                slot=q.slot,
                rendered_text=rendered,
                lang=ctx.lang,
            ))
        ctx.questions = questions

        cats = {q.category: sum(1 for s in selected if s.category == q.category)
                for q in selected}
        ctx.log(
            "stage.intake_qa.done",
            detail=f"bank={len(self._bank)} asked={len(questions)} categories={cats}",
        )
        return ctx

    # -- STT answer capture (called by the UI once audio exists) --------------
    def capture_answer(self, ctx: SessionContext, question_id: str,
                       audio_path: str) -> IntakeAnswer:
        """Transcribe a recorded answer and attach it to the session + summary."""
        stt = self._get_stt()
        result = stt.transcribe(audio_path, lang=ctx.lang)
        answer = IntakeAnswer(question_id=question_id, transcript=result.text, lang=ctx.lang)

        # Re-answering REPLACES. A patient who mis-speaks re-records the same
        # question, and appending would leave both takes attached — the doctor
        # would see two contradictory answers with no way to tell which is
        # current, and the stale one might be the one they act on.
        ctx.answers = [a for a in ctx.answers if a.question_id != question_id]
        ctx.answers.append(answer)
        if ctx.summary is not None:
            prior = ctx.summary.content.get("intake_answers", [])
            ctx.summary.content["intake_answers"] = [
                a for a in prior if a.get("question_id") != question_id
            ] + [{"question_id": question_id, "transcript": result.text, "lang": ctx.lang}]
        self.models.release("stt")
        ctx.log("stage.intake_qa.answer", detail=f"q={question_id} chars={len(result.text)}")
        return answer

    def _get_stt(self):
        try:
            return self.models.get("stt")
        except ImportError:      # faster-whisper missing -> stub
            from models.stt_stub import StubSTTAdapter

            self.models.release("stt")
            return self.models.get(
                "stt",
                factory=lambda logical_name, spec, env: StubSTTAdapter(
                    logical_name, {**spec, "device": "cpu"}, env),
            )
