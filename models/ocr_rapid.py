"""RapidOCR adapter — Apache-2.0 commercial-clean OCR (ONNX Runtime).

Drop-in alternative to PaddleOCR that avoids the paddlepaddle runtime while
keeping PP-OCR-family accuracy via ONNX mobile det/rec weights.

Install (current RapidAI package):
    pip install rapidocr onnxruntime

Swap in via config:
    ocr.primary.impl: rapidocr
"""

from __future__ import annotations

import numpy as np

from core.model_manager import register_adapter
from models.ocr_base import OCRAdapterBase, OCRPage, OCRToken
from models.ocr_paddle import _rows_to_text


class RapidOCRAdapter(OCRAdapterBase):
    default_vram_mb = 800

    def _build_engine(self):
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "RapidOCR not installed. `pip install rapidocr onnxruntime`, "
                "or swap ocr.primary.impl to 'stub_ocr'."
            ) from exc

        params: dict = {}
        # Prefer English recognition for printed lab reports (~99% English).
        langs = [str(x).lower() for x in self.spec.get("lang", ["en"])]
        if langs == ["en"]:
            # LangRec.EN when available; dotted params keep v3 flexible.
            try:
                from rapidocr import LangRec, OCRVersion, ModelType

                params.update({
                    "Rec.lang_type": LangRec.EN,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.MOBILE,
                    "Det.ocr_version": OCRVersion.PPOCRV5,
                    "Det.model_type": ModelType.MOBILE,
                })
            except Exception:
                pass

        limit = self.spec.get("det_limit_side_len")
        if limit:
            params["Det.limit_side_len"] = int(limit)
            params["Det.limit_type"] = str(self.spec.get("det_limit_type", "max"))

        # Orientation cls off — intake already deskews (matches paddle config).
        if not bool(self.spec.get("use_textline_orientation", False)):
            params["Global.use_cls"] = False

        if self.spec.get("det_model"):
            params["Det.model_path"] = str(self.spec["det_model"])
        if self.spec.get("rec_model"):
            params["Rec.model_path"] = str(self.spec["rec_model"])

        return RapidOCR(params=params) if params else RapidOCR()

    def _recognize(self, image: np.ndarray | None, source_path: str | None) -> OCRPage:
        if image is None:
            return OCRPage()
        out = self._engine(image)
        return self._page_from_output(out)

    def _page_from_output(self, out) -> OCRPage:
        """Support RapidOCROutput (v3) and legacy list-of-[box,text,score]."""
        tokens: list[OCRToken] = []

        # New API: RapidOCROutput with boxes / txts / scores
        boxes = getattr(out, "boxes", None)
        txts = getattr(out, "txts", None)
        scores = getattr(out, "scores", None)
        if boxes is not None and txts is not None:
            scores = scores or [1.0] * len(txts)
            for i, text in enumerate(txts):
                conf = float(scores[i]) if i < len(scores) else 1.0
                bbox = None
                if i < len(boxes):
                    try:
                        pts = boxes[i]
                        xs = [int(p[0]) for p in pts]
                        ys = [int(p[1]) for p in pts]
                        bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                    except (TypeError, ValueError, IndexError):
                        bbox = None
                tokens.append(OCRToken(text=str(text), confidence=conf, bbox=bbox))
            return OCRPage(text=_rows_to_text(tokens), tokens=tokens)

        # Legacy: (result_list, elapse) or bare list
        result = out
        if isinstance(out, tuple) and out:
            result = out[0]
        if not result:
            return OCRPage()
        for item in result:
            if not item or len(item) < 3:
                continue
            box, text, conf = item[0], item[1], item[2]
            bbox = None
            try:
                xs = [int(p[0]) for p in box]
                ys = [int(p[1]) for p in box]
                bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            except (TypeError, ValueError, IndexError):
                bbox = None
            tokens.append(OCRToken(text=str(text), confidence=float(conf), bbox=bbox))
        return OCRPage(text=_rows_to_text(tokens), tokens=tokens)


register_adapter(
    "rapidocr",
    lambda logical_name, spec, env: RapidOCRAdapter(logical_name, spec, env),
)
