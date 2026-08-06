"""[4] Summary Generation — the main model bake-off stage.

Loads the configured LLM via ModelManager (Phi-3.5-mini via Ollama is the
commercial primary; Qwen/MedGemma remain bake-off candidates; stub_llm for
CPU/no-deps), builds a structured-fill prompt from ctx.ocr fields, generates
JSON, parses it into SummarySchema, and runs the FAITHFULNESS GATE: any value
that does not trace to an OCR field is dropped and recorded, so the stored
summary is always faithful. The LLM is the only heavy model resident here
(OCR must already be unloaded).

Swap models by editing llm.primary in config/models.yaml; bench them with
`python -m bench.runner` (produces the stakeholder proof).

Tested/won/open: schema fill, faithfulness gate (drops injected hallucination),
load/unload, and stub fallback verified. Open: Phi prompt polish vs Qwen faith
gap; Sarvam/MedGemma accuracy/Hindi/latency numbers (see bench/).
"""

from __future__ import annotations

from core.context import SessionContext, SummaryDoc
from core.stage import Stage
from stages.faithfulness import (
    check_faithfulness, drop_hallucinations, reconcile_multimodal,
)
from stages.summary_build import build_prompt, parse_summary
from stages.summary_schema import SummarySchema


class SummaryStage(Stage):
    name = "summary"
    order = 4
    description = "OCR output -> structured Swasthya Sathi report draft."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._llm = None
        self._active_impl: str | None = None

    def _configured_impl(self) -> str:
        return self.config.models.get("llm", {}).get("primary", {}).get("impl", "stub_llm")

    def load(self) -> None:
        try:
            self._llm = self.models.get("llm")
            self._active_impl = self._configured_impl()
        except Exception:  # missing deps / server down / no weights -> stub
            from models.llm_stub import StubLLMAdapter

            self.models.release("llm")
            self._llm = self.models.get(
                "llm",
                factory=lambda logical_name, spec, env: StubLLMAdapter(
                    logical_name, {**spec, "device": "cpu"}, env
                ),
            )
            self._active_impl = f"{self._configured_impl()}->stub_llm(fallback)"

    def unload(self) -> None:
        self.models.release("llm")
        self._llm = None

    def _save_raw_debug(self, ctx: SessionContext, raw: str) -> None:
        """Persist the unparseable LLM response so the failure can be inspected."""
        try:
            from pathlib import Path

            debug_dir = Path(self.config.env.data_dir) / ctx.session_id
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "summary_raw_failed.txt").write_text(raw, encoding="utf-8")
        except OSError:
            pass  # debug artifact only — never fail the stage over it

    def _report_images(self, ctx: SessionContext) -> list[str]:
        """Processed report-page image paths, for the multimodal (text+image) path.

        CAPPED. Each page image costs hundreds of vision tokens, and an uncapped
        list made a real 16-page session unrunnable — MedGemma-4B INT4 on an 8 GB
        card never returned. The text of every page is already extracted by OCR
        (100% recall on the real-report bench); images are a supplementary
        cross-check, so reading the first N pages is a sound trade. Tune with
        summary.max_images; 0 disables the cap.
        """
        paths: list[str] = []
        for up in ctx.uploads:
            if up.type not in ("image", "pdf"):
                continue
            p = up.processed_path or up.path
            if p:
                paths.append(p)
        cap = int(self.config.stage_cfg("summary").get("max_images", 4))
        if cap > 0 and len(paths) > cap:
            self._dropped_images = len(paths) - cap
            return paths[:cap]
        self._dropped_images = 0
        return paths

    def run(self, ctx: SessionContext) -> SessionContext:
        if self._llm is None:
            self.load()

        ocr_fields = ctx.ocr.fields if ctx.ocr else []
        system, user = build_prompt(ocr_fields, patient_language=ctx.lang)

        # Multimodal path: only when enabled, the adapter supports images, and
        # images exist. In this path a vision model may read values off the page
        # image that OCR missed; those are reconciled below (kept for review,
        # never silently trusted) rather than dropped.
        stage_cfg = self.config.stage_cfg("summary")
        use_images = bool(stage_cfg.get("use_images", False))
        max_tokens = int(stage_cfg.get("max_tokens", 1024))
        # Scale the budget with the session: a 16-page report carries ~59 values,
        # and emitting them all costs far more than the 2-page default allows —
        # the summary was truncated to a fraction of the findings. ~45 tokens per
        # value plus room for the narrative, capped so a huge session cannot run
        # away.
        n_values = sum(1 for f in (ctx.ocr.fields if ctx.ocr else [])
                       if not f.name.endswith(" ref-range"))
        needed = 512 + 45 * n_values
        if needed > max_tokens:
            max_tokens = min(needed, int(stage_cfg.get("max_tokens_ceiling", 6144)))
        images = self._report_images(ctx) if use_images else []
        multimodal = bool(use_images and images and getattr(self._llm, "multimodal", False))
        if multimodal:
            raw = self._llm.generate(system, user, max_tokens=max_tokens, images=images)
        else:
            raw = self._llm.generate(system, user, max_tokens=max_tokens)

        try:
            parsed = parse_summary(raw)
            summary = SummarySchema.model_validate(parsed)
            # A repetition loop can emit the same finding many times; keep the first.
            seen: set[tuple] = set()
            deduped = []
            for f in summary.lab_findings:
                key = (f.analyte, f.value, f.unit, f.source_field)
                if key not in seen:
                    seen.add(key)
                    deduped.append(f)
            summary.lab_findings = deduped
        except Exception as exc:  # tolerant: a bad model response never crashes the pipeline
            summary = SummarySchema(patient_language=ctx.lang,
                                    unknowns=[f"parse_error: {type(exc).__name__}"])
            self._save_raw_debug(ctx, raw)
            ctx.log("stage.summary.parse_error",
                    detail=f"impl={self._active_impl} err={type(exc).__name__}")

        # Faithfulness gate. Text path: drop anything not traceable to OCR.
        # Multimodal path: keep OCR-verified findings; move image-only values to a
        # review bucket (surfaced, not trusted) instead of dropping them.
        report = check_faithfulness(summary, ocr_fields)
        unverified: list[dict] = []
        if multimodal:
            faithful, unverified = reconcile_multimodal(summary, ocr_fields)
        else:
            faithful = drop_hallucinations(summary, ocr_fields)

        content = faithful.model_dump()
        if unverified:
            content["unverified_image_findings"] = unverified

        version = (ctx.summary.version + 1) if ctx.summary else 1
        ctx.summary = SummaryDoc(version=version, content=content)

        ctx.log(
            "stage.summary.done",
            detail=(f"impl={self._active_impl} multimodal={multimodal} "
                    f"images={len(images)}"
                    + (f"(+{self._dropped_images} dropped by cap)"
                       if getattr(self, "_dropped_images", 0) else "")
                    + f" findings={len(faithful.lab_findings)} "
                    f"image_only={len(unverified)} "
                    f"faithfulness={report.faithfulness:.2f} issues={len(report.issues)}"),
        )
        return ctx
