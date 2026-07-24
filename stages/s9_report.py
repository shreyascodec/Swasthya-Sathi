"""[9] Final Report — assemble the versioned, tamper-evident Swasthya Sathi report.

Gathers everything the pipeline produced into one report bundle: the source-traced
lab findings and the deterministic interpretation flags (the clinical core), the
clinical image tags (report scans are excluded — they are OCR sources, not tagged
images), the medications, the intake questions with their spoken answers, the
patient narrative, and a provenance block (per-file hashes + the source-manifest
digest from stage [8]).

The bundle is then **versioned** (bump on every regeneration) and **content-hashed**
— a SHA-256 over a canonical serialization of the clinical content, deliberately
excluding the generation timestamp so the same inputs always yield the same digest.
That makes the report tamper-evident and de-duplicable: change any value and the
hash changes; regenerate identical data and it does not.

The audit entry carries counts + version + hash prefix only — never PHI content.

Future work (unchanged from the plan): PDF export (WeasyPrint, Devanagari) and a
FHIR-ish JSON bundle for the ABDM path. The assembled ``content`` here is the
source those exporters will render.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.context import FinalReport, SessionContext
from core.stage import Stage
from stages.s8_hashing import source_manifest_digest


def _basename(path: str | None) -> str | None:
    return Path(path).name if path else None


def assemble_content(ctx: SessionContext) -> dict:
    """Build the report content dict from the flowing context. Pure."""
    summary = ctx.summary.content if ctx.summary else {}
    answer_by_q = {a.question_id: a.transcript for a in ctx.answers}

    return {
        "patient_language": ctx.lang,
        "facility": summary.get("facility"),
        "doctor": summary.get("doctor"),
        "report_dates": summary.get("report_dates", []),
        # Clinical core — the interpretation flags are authoritative (rule-based);
        # the summary findings are the LLM's source-traced restatement.
        "lab_findings": summary.get("lab_findings", []),
        "interpretations": [f.model_dump() for f in ctx.interpretations],
        "medications": summary.get("medications", []),
        "narrative_en": summary.get("narrative_en", ""),
        # Clinical photos only (report scans were never tagged — see stage [3]).
        "image_tags": [t.model_dump() for t in ctx.image_tags],
        # Intake Q&A, each question paired with its transcribed answer (if any).
        "intake": [
            {
                "pattern_id": q.pattern_id,
                "question": q.rendered_text,
                "answer": answer_by_q.get(q.id),
                "lang": q.lang,
            }
            for q in ctx.questions
        ],
        "unknowns": summary.get("unknowns", []),
        # Provenance: which exact files this report was built from.
        "sources": [
            {
                "file": _basename(u.path),
                "sha256": u.sha256,
                "type": u.type,
                "is_document": u.is_document,
            }
            for u in ctx.uploads
        ],
        "source_manifest_sha256": source_manifest_digest(ctx),
    }


def content_digest(content: dict) -> str:
    """Deterministic SHA-256 over the clinical content (timestamp excluded)."""
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReportStage(Stage):
    name = "report"
    order = 9
    description = "Assemble + version + hash the Swasthya Sathi report."

    def run(self, ctx: SessionContext) -> SessionContext:
        content = assemble_content(ctx)
        digest = content_digest(content)

        # Version per generation; a prior report in the session bumps the number.
        prev = ctx.report.version if ctx.report else 0
        ctx.report = FinalReport(version=prev + 1, sha256=digest, content=content)

        answered = sum(1 for i in content["intake"] if i["answer"])
        ctx.log(
            "stage.report.done",
            detail=(f"v{ctx.report.version} sha={digest[:12]} "
                    f"findings={len(content['lab_findings'])} "
                    f"flags={len(content['interpretations'])} "
                    f"images={len(content['image_tags'])} "
                    f"answers={answered}/{len(content['intake'])}"),
        )
        return ctx
