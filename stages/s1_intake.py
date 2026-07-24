"""[1] Intake & Preprocess.

Reads each raw upload on the SessionContext, renders pages (image or PDF),
runs deskew -> denoise -> DPI/size-normalize, applies the classical-CV quality
gate (Laplacian-variance blur + brightness), and stores the processed artifact
with a compress-then-hash SHA-256. Blurry/badly-lit pages are flagged
``needs_rescan``. No model, no GPU (PLAN.md Phase 1).

Input  : ctx.uploads[*].source_path (raw file), type
Output : ctx.uploads rewritten to processed pages with path, sha256,
         quality_ok, needs_rescan, blur_score, brightness.

Tested/won/open: quality gate + compress-then-hash verified on synthetic sharp/
blurry/dark images and a generated PDF. Open: real Indian-report tuning of the
blur/brightness thresholds; multi-column deskew robustness.
"""

from __future__ import annotations

from pathlib import Path

from core.context import SessionContext, UploadedFile
from core.stage import Stage
from stages import imaging
from stages.imaging import IntakeParams


class IntakeStage(Stage):
    name = "intake"
    order = 1
    description = "Upload reports/images, clean, quality-gate."

    def _params(self) -> IntakeParams:
        return IntakeParams.from_cfg(self.config.stage_cfg("intake"))

    def _storage_dir(self, session_id: str, params: IntakeParams) -> Path:
        return Path(self.config.env.data_dir) / session_id / params.storage_subdir

    def run(self, ctx: SessionContext) -> SessionContext:
        params = self._params()
        out_dir = self._storage_dir(ctx.session_id, params)

        processed: list[UploadedFile] = []
        rescan_count = 0

        for upload in ctx.uploads:
            # Idempotent: keep already-processed entries untouched.
            if upload.processed_path is not None:
                processed.append(upload)
                if upload.needs_rescan:
                    rescan_count += 1
                continue

            source = upload.source_path or upload.path
            file_type = upload.type if upload.type in ("image", "pdf") else imaging.guess_type(source)

            # Digital-PDF fast path seam: per-page embedded text (or None when
            # scanned) rides along on the upload so OCR can skip the engine.
            text_layers: list[str | None] = []
            if file_type == "pdf" and params.extract_text_layer:
                text_layers = imaging.pdf_text_layers(source, params.text_layer_min_words)

            pages = imaging.read_pages(source, file_type, params)
            for idx, page in enumerate(pages):
                proc = imaging.preprocess(page, params)
                quality = imaging.quality_metrics(proc, params)
                name = f"{upload.id}_p{idx}"
                stored_path, sha256 = imaging.store_image(proc, out_dir, name, params)

                if quality.needs_rescan:
                    rescan_count += 1

                # PDF pages are documents by construction; photos go through the
                # classical white-paper gate so OCR can skip clinical images.
                is_document = True if file_type == "pdf" else imaging.looks_like_document(proc, params)

                processed.append(
                    UploadedFile(
                        id=name,
                        path=stored_path,
                        type=file_type,
                        sha256=sha256,
                        quality_ok=not quality.needs_rescan,
                        source_path=source,
                        processed_path=stored_path,
                        page=idx,
                        blur_score=round(quality.blur_score, 2),
                        brightness=round(quality.brightness, 2),
                        needs_rescan=quality.needs_rescan,
                        is_document=is_document,
                        text_layer=text_layers[idx] if idx < len(text_layers) else None,
                    )
                )

        ctx.uploads = processed
        # Audit records type/version counts only — never file content.
        docs = sum(1 for u in processed if u.is_document)
        with_layer = sum(1 for u in processed if u.text_layer)
        ctx.log(
            "stage.intake.done",
            detail=f"pages={len(processed)} rescan={rescan_count} docs={docs} text_layer={with_layer}",
        )
        return ctx
