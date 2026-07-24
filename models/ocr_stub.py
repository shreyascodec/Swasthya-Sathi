"""Stub OCR engine — the config-swappable CPU/no-deps fallback.

Not a real recognizer. It sources text from, in order:
  1. a sidecar ``<source_path>.ocr.json`` with tokens (simulates engine output,
     including per-token confidence — used by tests and for canned demos),
  2. a PDF's embedded text layer (via PyMuPDF), or
  3. a sidecar ``<source_path>.txt``.

This lets the full extraction pipeline + ModelManager load/unload seam run
end-to-end without downloading PaddleOCR/Surya. Swap to a real engine by editing
``ocr.primary.impl`` in config/models.yaml — no code change.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.model_manager import register_adapter
from models.ocr_base import OCRAdapterBase, OCRPage, OCRToken


class StubOCRAdapter(OCRAdapterBase):
    default_vram_mb = 0

    def _build_engine(self):
        return {"stub": True}  # nothing to load

    def _recognize(self, image: np.ndarray | None, source_path: str | None) -> OCRPage:
        if not source_path:
            return OCRPage()
        src = Path(source_path)

        sidecar_json = Path(str(src) + ".ocr.json")
        if sidecar_json.exists():
            return self._from_json(sidecar_json)

        if src.suffix.lower() == ".pdf":
            page = self._from_pdf(src)
            if page is not None:
                return page

        sidecar_txt = Path(str(src) + ".txt")
        if sidecar_txt.exists():
            text = sidecar_txt.read_text(encoding="utf-8")
            return self._page_from_text(text, confidence=0.99)

        return OCRPage()

    def _from_json(self, path: Path) -> OCRPage:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_tokens = data.get("tokens", data) if isinstance(data, dict) else data
        tokens = [
            OCRToken(text=str(t["text"]), confidence=float(t.get("confidence", 1.0)))
            for t in raw_tokens
        ]
        text = data.get("text") if isinstance(data, dict) else None
        if not text:
            text = "\n".join(t.text for t in tokens)
        return OCRPage(text=text, tokens=tokens)

    def _from_pdf(self, path: Path) -> OCRPage | None:
        try:
            import fitz
        except ImportError:  # pragma: no cover
            return None
        chunks: list[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                chunks.append(page.get_text())
        return self._page_from_text("\n".join(chunks), confidence=0.99)

    @staticmethod
    def _page_from_text(text: str, confidence: float) -> OCRPage:
        tokens = [
            OCRToken(text=line.strip(), confidence=confidence)
            for line in text.splitlines() if line.strip()
        ]
        return OCRPage(text=text, tokens=tokens)


register_adapter("stub_ocr", lambda logical_name, spec, env: StubOCRAdapter(logical_name, spec, env))
