"""PaddleOCR adapter (primary OCR engine). Lazy-imports paddleocr on load.

Install (per phase, not in the lean Phase-0/1 set):
    pip install paddlepaddle paddleocr          # or paddlepaddle-gpu on CUDA

Targets PaddleOCR 3.x (the ``.predict()`` API with ``rec_texts``/``rec_scores``/
``rec_polys``). The old 2.x ``use_gpu``/``show_log``/``.ocr(cls=True)`` surface is
gone. Kept thin: PaddleOCR quirks stay here so the stage/extractor never see them.
"""

from __future__ import annotations

import numpy as np

from core.env import EnvProfile
from core.model_manager import register_adapter
from models.ocr_base import OCRAdapterBase, OCRPage, OCRToken


class PaddleOCRAdapter(OCRAdapterBase):
    default_vram_mb = 1024

    def _build_engine(self):
        try:
            from paddleocr import PaddleOCR  # heavy; only imported when loaded
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "PaddleOCR not installed. `pip install paddlepaddle paddleocr` "
                "(or paddlepaddle-gpu on CUDA), or swap ocr.primary.impl to "
                "'stub_ocr' in config/models.yaml."
            ) from exc

        langs = self.spec.get("lang", ["en"])
        lang = "en" if "en" in langs else langs[0]
        # 3.x auto-selects device from the installed paddle build; angle cls is now
        # 'use_textline_orientation'. Doc pre-processing off (our intake already
        # deskews/denoises) for speed.
        # Speed knobs come from the ocr.primary spec (config/models.yaml):
        #   use_textline_orientation — off by default: intake already deskews, and
        #     the per-line classifier costs ~10-20% on upright printed reports.
        #   det_model/rec_model — PP-OCRv5 *mobile* by default (2-4x faster than
        #     the server default at a small accuracy cost on printed English).
        #   det_limit_side_len — caps detection input resolution.
        #   enable_mkldnn — False default: paddlepaddle 3.x oneDNN/PIR CPU crash
        #     (ConvertPirAttribute2RuntimeAttribute) on Windows; flip per machine.
        kwargs = dict(
            lang=lang,
            use_textline_orientation=bool(self.spec.get("use_textline_orientation", False)),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            enable_mkldnn=bool(self.spec.get("enable_mkldnn", False)),
        )
        det_model = self.spec.get("det_model")
        rec_model = self.spec.get("rec_model")
        if det_model:
            kwargs["text_detection_model_name"] = str(det_model)
        if rec_model:
            kwargs["text_recognition_model_name"] = str(rec_model)
        limit = self.spec.get("det_limit_side_len")
        if limit:
            kwargs["text_det_limit_side_len"] = int(limit)
            kwargs["text_det_limit_type"] = str(self.spec.get("det_limit_type", "max"))
        return PaddleOCR(**kwargs)

    def _recognize(self, image: np.ndarray | None, source_path: str | None) -> OCRPage:
        if image is None:
            return OCRPage()
        result = self._engine.predict(image)  # list of OCRResult (dict-like), 1/image
        return self._page_from_results(result or [])

    def _recognize_batch(
        self, images: list[np.ndarray | None], source_paths: list[str | None]
    ) -> list[OCRPage]:
        # One predict() over all pages: Paddle pipelines det/rec across images
        # and per-call overhead is paid once. None images (unreadable) stay empty.
        pages: list[OCRPage] = [OCRPage() for _ in images]
        idx = [i for i, im in enumerate(images) if im is not None]
        if not idx:
            return pages
        results = self._engine.predict([images[i] for i in idx]) or []
        for j, i in enumerate(idx):
            if j < len(results):
                pages[i] = self._page_from_results([results[j]])
        return pages

    def _page_from_results(self, results) -> OCRPage:
        tokens: list[OCRToken] = []
        for res in results:
            texts = res.get("rec_texts", []) or []
            scores = res.get("rec_scores", []) or []
            polys = res.get("rec_polys", None)
            if polys is None:
                polys = res.get("dt_polys", []) or []
            for i, text in enumerate(texts):
                conf = float(scores[i]) if i < len(scores) else 1.0
                bbox = None
                if i < len(polys):
                    pts = polys[i]
                    xs = [int(p[0]) for p in pts]
                    ys = [int(p[1]) for p in pts]
                    bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                tokens.append(OCRToken(text=str(text), confidence=conf, bbox=bbox))

        # Reconstruct table ROWS from geometry: report tables put an analyte and
        # its value/unit/range in separate detections on the same visual line.
        # The field extractor expects them together, so join tokens by row.
        return OCRPage(text=_rows_to_text(tokens), tokens=tokens)


def _rows_to_text(tokens: list[OCRToken]) -> str:
    """Group tokens into visual rows by y-overlap, order each row left-to-right,
    and join with spaces — turning column-split table cells back into readable
    lines like 'Hemoglobin 9.5 g/dL 13.0-17.0'. Tokens without a bbox fall back to
    detection order."""
    placed = [t for t in tokens if t.bbox]
    if not placed:
        return "\n".join(t.text for t in tokens)

    heights = sorted(t.bbox[3] for t in placed)
    thresh = max(6.0, 0.6 * heights[len(heights) // 2])  # 60% of median row height

    def y_center(t: OCRToken) -> float:
        return t.bbox[1] + t.bbox[3] / 2.0

    rows: list[list[OCRToken]] = []
    for tok in sorted(placed, key=y_center):
        yc = y_center(tok)
        row = rows[-1] if rows else None
        if row is not None and abs(yc - y_center(row[0])) <= thresh:
            row.append(tok)
        else:
            rows.append([tok])

    lines = []
    for row in rows:
        row.sort(key=lambda t: t.bbox[0])
        lines.append(" ".join(t.text for t in row))
    return "\n".join(lines)


register_adapter("paddleocr", lambda logical_name, spec, env: PaddleOCRAdapter(logical_name, spec, env))
