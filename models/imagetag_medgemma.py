"""MedGemma-4B vision tagger — real skin/eye/wound/oral typing, zero-shot.

The MobileNetV3 tagger needs a fine-tuned 4-class checkpoint that does not
exist yet, so it tags everything "unknown". This adapter reuses the same
MedGemma-4B weights the summary stage uses (INT4, one heavy model resident at
a time — image_tag runs alone, so VRAM policy holds) and asks it to classify
the image type zero-shot. Output stays TYPE + confidence only: the prompt asks
for nothing else and the stage schema cannot store anything else, so the
no-diagnosis invariant is intact.

Swap back to mobilenetv3 in config/models.yaml once a trained checkpoint lands.
"""

from __future__ import annotations

import numpy as np

from core.model_manager import register_adapter
from models.imagetag_base import ImageTagAdapterBase, TagResult

_SYSTEM = (
    "You classify a single clinical image into exactly one type for routing "
    "purposes. You do NOT diagnose. Types:\n"
    '  "skin"  - photo of skin / a skin lesion or rash\n'
    '  "eye"   - photo of an eye, retina/fundus image, or an ophthalmic report '
    "whose subject is an eye/fundus image\n"
    '  "wound" - photo of a wound, cut, burn or ulcer\n'
    '  "oral"  - photo of the mouth, teeth, tongue or throat\n'
    '  "unknown" - anything else (plain text documents, non-clinical photos, '
    "unclear images)\n"
    'Return ONLY a JSON object: {"type": "<one of the types>", '
    '"confidence": <number 0..1>} — no prose, no code fences.'
)

_USER = "Classify this image."


class MedGemmaImageTagAdapter(ImageTagAdapterBase):
    default_vram_mb = 3700

    def _build_model(self):
        from models.llm_medgemma_mm import MedGemmaMMAdapter

        spec = {
            "model": self.spec.get("model", "google/medgemma-4b-it"),
            "quant": self.spec.get("quant", "int4"),
            "device": self.device,
            "vram_mb": self._vram_mb,
        }
        adapter = MedGemmaMMAdapter(self.logical_name, spec, self.env)
        adapter.load()
        return adapter

    def unload(self) -> None:
        if self._model is not None:
            self._model.unload()
        self._model = None

    def _classify(self, image: np.ndarray | None, source_path: str | None) -> TagResult:
        pil = self._to_pil(image, source_path)
        if pil is None:
            return TagResult()
        raw = self._model.generate(_SYSTEM, _USER, max_tokens=64, images=[pil])
        return self._parse(raw)

    @staticmethod
    def _to_pil(image: np.ndarray | None, source_path: str | None):
        from PIL import Image

        if image is not None:
            return Image.fromarray(image[:, :, ::-1])  # BGR (cv2) -> RGB
        if source_path:
            try:
                return Image.open(source_path).convert("RGB")
            except OSError:
                return None
        return None

    def _parse(self, raw: str) -> TagResult:
        from stages.summary_build import parse_summary

        try:
            d = parse_summary(raw)
        except Exception:
            return TagResult()
        tag_type = str(d.get("type", "unknown")).lower().strip()
        try:
            score = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
        except (TypeError, ValueError):
            score = 0.0
        if tag_type not in set(self.classes) | {"unknown"}:
            tag_type = "unknown"
        return TagResult(type=tag_type, score=score)


register_adapter(
    "imagetag_medgemma",
    lambda logical_name, spec, env: MedGemmaImageTagAdapter(logical_name, spec, env),
)
