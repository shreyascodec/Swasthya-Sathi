"""Surya OCR adapter (Indic fallback). Lazy-imports surya on load.

Surya has strong Indic-script coverage; swap it in via config to bench against
PaddleOCR on Devanagari/regional reports. Install per phase:
    pip install surya-ocr
"""

from __future__ import annotations

import numpy as np

from core.model_manager import register_adapter
from models.ocr_base import OCRAdapterBase, OCRPage, OCRToken


class SuryaAdapter(OCRAdapterBase):
    default_vram_mb = 1536

    def _build_engine(self):
        try:
            from PIL import Image  # noqa: F401
            from surya.ocr import run_ocr
            from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_proc
            from surya.model.recognition.model import load_model as load_rec_model
            from surya.model.recognition.processor import load_processor as load_rec_proc
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "Surya not installed. `pip install surya-ocr`, or swap "
                "ocr.primary.impl to 'stub_ocr' in config/models.yaml."
            ) from exc

        return {
            "run_ocr": run_ocr,
            "det_model": load_det_model(),
            "det_proc": load_det_proc(),
            "rec_model": load_rec_model(),
            "rec_proc": load_rec_proc(),
            "langs": self.spec.get("lang", ["en", "hi"]),
        }

    def _recognize(self, image: np.ndarray | None, source_path: str | None) -> OCRPage:
        if image is None:
            return OCRPage()
        import cv2
        from PIL import Image

        eng = self._engine
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        preds = eng["run_ocr"](
            [pil], [eng["langs"]], eng["det_model"], eng["det_proc"],
            eng["rec_model"], eng["rec_proc"],
        )
        tokens: list[OCRToken] = []
        lines: list[str] = []
        for line in preds[0].text_lines:
            conf = float(getattr(line, "confidence", 1.0) or 1.0)
            tokens.append(OCRToken(text=line.text, confidence=conf))
            lines.append(line.text)
        return OCRPage(text="\n".join(lines), tokens=tokens)


register_adapter("surya", lambda logical_name, spec, env: SuryaAdapter(logical_name, spec, env))
