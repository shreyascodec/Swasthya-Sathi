"""SessionContext and the per-session data shapes.

SessionContext is the single object that flows through the pipeline. Each stage
reads what it needs and writes its output back; stages never talk to each other
directly (ARCHITECTURE.md section 3). This makes any stage runnable standalone
against a hand-built or saved context.

These are the Phase-0 shapes. Fields will be fleshed out as each stage is
implemented, but the seams exist now so no-op stages can pass a context through.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadedFile(BaseModel):
    id: str
    path: str                        # canonical stored (processed) artifact path
    type: str = "unknown"            # image | pdf | unknown
    sha256: str | None = None        # hash of the STORED file (compress-then-hash)
    quality_ok: bool | None = None   # set by the Phase-1 quality gate

    # Phase-1 intake/preprocess fields:
    source_path: str | None = None   # original uploaded file
    processed_path: str | None = None  # deskewed/denoised/normalized artifact
    page: int = 0                    # page index (multi-page PDFs -> one per page)
    blur_score: float | None = None  # variance-of-Laplacian
    brightness: float | None = None  # mean grayscale (0-255)
    needs_rescan: bool = False       # quality gate failed -> prompt rescan

    # OCR-routing hints (set at intake; None = unknown -> OCR runs anyway):
    is_document: bool | None = None  # classical doc-vs-photo gate; False lets OCR skip the page
    text_layer: str | None = None    # embedded PDF text layer; set -> OCR engine not needed


class OCRField(BaseModel):
    name: str                        # e.g. "hemoglobin", "date", "drug"
    value: str
    unit: str | None = None
    confidence: float | None = None
    low_confidence: bool = False

    # Provenance: which uploaded page this field was read from. Without it the
    # field list is flat and a summary LLM cannot tell which facility/doctor/date
    # a value belongs to — it guessed, and attributed one lab's results to
    # another lab's doctor on a two-report session.
    page_index: int | None = None    # 0-based position in ctx.uploads
    page_id: str | None = None       # UploadedFile.id it came from


class OCRResult(BaseModel):
    raw_text: str = ""
    fields: list[OCRField] = Field(default_factory=list)
    engine: str | None = None


class ImageTag(BaseModel):
    upload_id: str
    type: Literal["skin", "eye", "wound", "oral", "unknown"] = "unknown"
    quality_ok: bool = True
    score: float | None = None
    # NOTE: type + quality only. Never a diagnosis (product invariant).


class SummaryDoc(BaseModel):
    version: int = 1
    generated_at: datetime = Field(default_factory=_utcnow)
    content: dict[str, Any] = Field(default_factory=dict)


class LabFlag(BaseModel):
    analyte: str
    value: str
    unit: str | None = None
    ref_range: str | None = None
    status: Literal["low", "normal", "high", "critical", "unknown"] = "unknown"
    high_priority: bool = False


class IntakeQuestion(BaseModel):
    id: str
    pattern_id: str
    slot: str | None = None
    rendered_text: str = ""
    lang: str = "hi"


class IntakeAnswer(BaseModel):
    question_id: str
    transcript: str = ""
    lang: str = "hi"


class AudioClip(BaseModel):
    id: str
    path: str
    lang: str = "hi"
    kind: str = "tts"                # tts | recorded-answer
    duration_ms: int | None = None   # timing seam for future Wav2Lip attach


class FinalReport(BaseModel):
    version: int = 1
    sha256: str | None = None
    generated_at: datetime = Field(default_factory=_utcnow)
    content: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """Audit entries record type/version, NOT content (privacy invariant)."""

    ts: datetime = Field(default_factory=_utcnow)
    actor: str = "system"
    action: str = ""
    detail: str | None = None        # type/version only; never PHI content


class SessionContext(BaseModel):
    """The single object that flows through every stage."""

    session_id: str
    lang: str = "hi"                 # patient language; drives STT/TTS/model-fill
    created_at: datetime = Field(default_factory=_utcnow)

    uploads: list[UploadedFile] = Field(default_factory=list)
    ocr: OCRResult | None = None
    image_tags: list[ImageTag] = Field(default_factory=list)
    summary: SummaryDoc | None = None
    interpretations: list[LabFlag] = Field(default_factory=list)
    questions: list[IntakeQuestion] = Field(default_factory=list)
    answers: list[IntakeAnswer] = Field(default_factory=list)
    audio_out: list[AudioClip] = Field(default_factory=list)
    report: FinalReport | None = None
    audit: list[AuditEvent] = Field(default_factory=list)

    def log(self, action: str, actor: str = "system", detail: str | None = None) -> None:
        """Append an audit event. Keep ``detail`` to type/version, never content."""
        self.audit.append(AuditEvent(actor=actor, action=action, detail=detail))
