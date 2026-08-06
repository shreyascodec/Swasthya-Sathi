"""[2] OCR Extraction — first model bench-off stage.

Optimized routing (ocrplan.md): each page takes the cheapest path that yields
text, and the engine is only built if at least one page actually needs it.

  1. skip     — intake marked the page a non-document (clinical photo): no text.
  2. text     — digital PDF with an embedded text layer: consumed directly,
                faster AND more accurate than OCR.
  3. cache    — page hash + engine spec seen before: stored result reused.
  4. engine   — remaining pages go through the configured OCR engine in ONE
                batched call (RapidOCR primary / Surya fallback / stub_ocr).

Then the deterministic field extractor -> ctx.ocr (raw text + structured fields
with confidence). Low-confidence fields are flagged for review. Engine load is
timed separately from inference (load_s vs ocr_s in the audit detail) and VRAM
frees on exit unless ocr.primary.keep_warm is set (free for CPU engines; on GPU
the ModelManager policy still evicts it when the LLM loads).

Swap engines by editing ocr.primary.impl in config/models.yaml — no code change.

Tested/won/open: extraction + confidence flagging + load/unload + engine-swap
verified via the stub engine and a PDF text layer. Open: real RapidOCR vs Surya
accuracy bench on Indian printed reports (>=90% target) once samples are in hand.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import cv2

from core.context import OCRResult, SessionContext
from core.stage import Stage
from models.ocr_base import OCRPage, OCRToken
from stages.ocr_extract import extract_fields


class OCRStage(Stage):
    name = "ocr"
    order = 2
    description = "Report image -> raw text + structured fields."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._engine = None
        self._active_impl: str | None = None
        self._load_s: float = 0.0

    def _spec(self) -> dict:
        return self.config.models.get("ocr", {}).get("primary", {})

    def _configured_impl(self) -> str:
        return self._spec().get("impl", "stub_ocr")

    def _engine_impl(self) -> str:
        return self._active_impl or self._configured_impl()

    def _threshold(self) -> float:
        return float(self.config.stage_cfg("ocr").get("low_confidence_threshold", 0.80))

    # -- engine lifecycle ---------------------------------------------------
    def load(self) -> None:
        # Deliberately lazy: pages served by the text-layer / cache / skip fast
        # paths must not pay engine init. _ensure_engine() runs on first need.
        return None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        impl = self._configured_impl()
        t0 = time.perf_counter()
        try:
            self._engine = self.models.get("ocr")   # loads; enforces VRAM policy
            self._active_impl = impl
        except ImportError:
            # Graceful degradation to the stub engine when the configured
            # engine's deps are absent (architecture: CPU/reduced/stub mode).
            # No crash; the fallback is recorded in the audit trail.
            from models.ocr_stub import StubOCRAdapter

            self.models.release("ocr")
            self._engine = self.models.get(
                "ocr",
                factory=lambda logical_name, spec, env: StubOCRAdapter(
                    logical_name, {**spec, "device": "cpu"}, env
                ),
            )
            self._active_impl = f"{impl}->stub_ocr(fallback)"
        self._load_s = time.perf_counter() - t0

    def unload(self) -> None:
        # keep_warm (ocr.primary in models.yaml) skips the release so repeat
        # runs pay no engine re-init. Free on CPU; on GPU the ModelManager's
        # max_resident_gpu_models policy still evicts it before the LLM loads.
        self._engine = None
        if self._spec().get("keep_warm", False):
            return
        self.models.release("ocr")               # frees VRAM on the 4060

    # -- result cache (keyed on page sha256 + engine spec) -------------------
    def _cache_dir(self) -> Path | None:
        cfg = self.config.stage_cfg("ocr")
        if not cfg.get("cache", True):
            return None
        d = Path(self.config.env.data_dir) / str(cfg.get("cache_subdir", "ocr_cache"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _cache_path(self, cache_dir: Path, sha256: str) -> Path:
        # New engine or changed engine config = new key: invalidation is automatic.
        spec_hash = hashlib.sha256(
            json.dumps(self._spec(), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
        return cache_dir / f"{sha256}_{spec_hash}.json"

    @staticmethod
    def _page_to_json(page: OCRPage) -> dict:
        return {
            "text": page.text,
            "tokens": [
                {"text": t.text, "confidence": t.confidence, "bbox": list(t.bbox) if t.bbox else None}
                for t in page.tokens
            ],
        }

    @staticmethod
    def _page_from_json(data: dict) -> OCRPage:
        tokens = [
            OCRToken(
                text=str(t["text"]),
                confidence=float(t.get("confidence", 1.0)),
                bbox=tuple(t["bbox"]) if t.get("bbox") else None,
            )
            for t in data.get("tokens", [])
        ]
        return OCRPage(text=str(data.get("text", "")), tokens=tokens)

    @staticmethod
    def _page_from_text_layer(text: str) -> OCRPage:
        # Embedded PDF text is ground truth: confidence 1.0, no bboxes needed
        # (the extractor's row-joining is only for engine-split table cells).
        tokens = [
            OCRToken(text=line.strip(), confidence=1.0)
            for line in text.splitlines() if line.strip()
        ]
        return OCRPage(text=text, tokens=tokens)

    # -- run ------------------------------------------------------------------
    def run(self, ctx: SessionContext) -> SessionContext:
        cfg = self.config.stage_cfg("ocr")
        skip_non_docs = bool(cfg.get("skip_non_documents", True))
        use_text_layer = bool(cfg.get("use_text_layer", True))
        cache_dir = self._cache_dir()

        pages: list[OCRPage | None] = [None] * len(ctx.uploads)
        pending: list[int] = []
        n_skipped = n_layer = n_cached = 0

        for i, upload in enumerate(ctx.uploads):
            if skip_non_docs and upload.is_document is False:
                pages[i] = OCRPage()             # clinical photo: nothing to read
                n_skipped += 1
                continue
            if use_text_layer and upload.text_layer:
                pages[i] = self._page_from_text_layer(upload.text_layer)
                n_layer += 1
                continue
            if cache_dir is not None and upload.sha256:
                cache_file = self._cache_path(cache_dir, upload.sha256)
                if cache_file.exists():
                    try:
                        pages[i] = self._page_from_json(
                            json.loads(cache_file.read_text(encoding="utf-8"))
                        )
                        n_cached += 1
                        continue
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        pass                     # corrupt entry -> re-OCR below
            pending.append(i)

        ocr_s = 0.0
        if pending:
            self._ensure_engine()
            images, sources = [], []
            for i in pending:
                upload = ctx.uploads[i]
                img_path = upload.processed_path or upload.path
                images.append(cv2.imread(img_path) if img_path else None)
                sources.append(upload.source_path)
            t0 = time.perf_counter()
            recognized = self._engine.recognize_batch(images, sources)
            ocr_s = time.perf_counter() - t0
            for j, i in enumerate(pending):
                pages[i] = recognized[j]
                if cache_dir is not None and ctx.uploads[i].sha256:
                    self._cache_path(cache_dir, ctx.uploads[i].sha256).write_text(
                        json.dumps(self._page_to_json(recognized[j])), encoding="utf-8"
                    )

        combined = OCRPage()
        for page in pages:
            if page is None:
                continue
            if page.text:
                combined.text += (("\n\n" if combined.text else "") + page.text)
            combined.tokens.extend(page.tokens)

        engine_label = self._engine_impl() if pending else "bypass(text_layer/cache)"

        # Extract PER PAGE so every field carries provenance. Concatenating first
        # produced a flat list in which a summary LLM could not tell which lab or
        # doctor a value belonged to — it guessed, and cross-attributed results
        # between two different labs in one session. Cross-page dedup is dropped
        # deliberately: the same analyte measured on two reports is two results,
        # not a duplicate.
        threshold = self._threshold()
        fields = []
        for i, page in enumerate(pages):
            if page is None or not (page.text or page.tokens):
                continue
            upload = ctx.uploads[i] if i < len(ctx.uploads) else None
            fields.extend(extract_fields(
                page.text, page.tokens, threshold,
                page_index=i,
                page_id=getattr(upload, "id", None),
            ))
        ctx.ocr = OCRResult(
            raw_text=combined.text,
            fields=fields,
            engine=engine_label,
        )

        low_conf = sum(1 for f in fields if f.low_confidence)
        ctx.log(
            "stage.ocr.done",
            detail=(
                f"engine={engine_label} fields={len(fields)} low_conf={low_conf} "
                f"pages={len(ctx.uploads)} ocr_pages={len(pending)} text_layer={n_layer} "
                f"cached={n_cached} skipped={n_skipped} "
                f"load_s={self._load_s:.2f} ocr_s={ocr_s:.2f}"
            ),
        )
        return ctx
