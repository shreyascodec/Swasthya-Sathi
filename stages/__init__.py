"""Pipeline stages, ordered 1..9 (ARCHITECTURE.md section 2).

Phase 0 ships no-op stubs: each implements the Stage ABC, logs an audit event,
and passes the SessionContext through unchanged. Real logic is added one phase
at a time per PLAN.md. ``build_pipeline`` returns the ordered stage instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing stage modules at package import time
    from core.env import AppConfig
    from core.model_manager import ModelManager
    from core.stage import Stage


def _stage_classes() -> list[type]:
    """Import stage classes lazily so importing the ``stages`` package (e.g. a
    pure helper like ``stages.summary_build``) does not pull in every stage and
    its model adapters — which would create circular imports."""
    from stages.s1_intake import IntakeStage
    from stages.s2_ocr import OCRStage
    from stages.s3_imagetag import ImageTagStage
    from stages.s4_summary import SummaryStage
    from stages.s5_interpret import InterpretStage
    from stages.s6_intake_qa import IntakeQAStage
    from stages.s7_voice import VoiceStage
    from stages.s8_hashing import HashingStage
    from stages.s9_report import ReportStage

    return [
        IntakeStage, OCRStage, ImageTagStage, SummaryStage, InterpretStage,
        IntakeQAStage, VoiceStage, HashingStage, ReportStage,
    ]


def build_pipeline(config: "AppConfig", models: "ModelManager") -> list["Stage"]:
    """Instantiate all stages in pipeline order."""
    stages = [cls(config, models) for cls in _stage_classes()]
    return sorted(stages, key=lambda s: s.order)
