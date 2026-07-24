"""MobileNetV3 image-tagging adapter. Lazy-imports torch/torchvision on load.

4-class head (skin/eye/wound/oral). ~100x faster than the MedGemma-4B vision
tagger (sub-100 ms vs ~13 s per image) and ~18x smaller in VRAM, because typing
an image is a 4-way classification, not a task that needs a 4B language model.

Weights resolution, in order:
  1. ``spec['weights']`` — a fine-tuned 4-class checkpoint (train it with
     ``python -m bench.train_imagetag``). This is the only mode whose *type*
     output means anything.
  2. ImageNet-pretrained backbone + an UNTRAINED head, when no checkpoint is
     present. The backbone is real but the head is random, so predictions are
     meaningless; the adapter reports score 0.0 so the stage's min_score gate
     coerces every result to "unknown" rather than emitting confident noise.

Offline-first: the ImageNet backbone is fetched once into the torch hub cache
and reused; set ``spec['pretrained']: false`` to forbid the fetch entirely.

Install per phase: pip install torch torchvision
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from core.model_manager import register_adapter
from models.imagetag_base import ImageTagAdapterBase, TagResult

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_weights(spec_path: str | None) -> Path | None:
    """Resolve the checkpoint path against the repo root, not the CWD.

    models.yaml carries a repo-relative path; resolving it against the process
    CWD silently degrades to the untrained head whenever the app is launched
    from elsewhere (a shortcut, a service, a different drive).
    """
    if not spec_path:
        return None
    p = Path(spec_path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p if p.exists() else None


class MobileNetV3Adapter(ImageTagAdapterBase):
    default_vram_mb = 200

    def _build_model(self):
        try:
            import torch
            import torchvision
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "torch/torchvision not installed. `pip install torch torchvision`, "
                "or swap image_tag.primary.impl to 'stub_imagetag' in models.yaml."
            ) from exc

        self._torch = torch
        weights_path = _resolve_weights(self.spec.get("weights"))
        self._trained = weights_path is not None

        # A random backbone learns nothing useful from a small head-only fine-tune,
        # so start from ImageNet features unless explicitly forbidden (offline box).
        backbone = None
        if self.spec.get("pretrained", True) and not self._trained:
            backbone = torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        model = torchvision.models.mobilenet_v3_small(weights=backbone)
        in_features = model.classifier[-1].in_features
        # Trained checkpoints carry one extra "other" logit (non-clinical input:
        # junk, scanned report pages, flat fields) that maps to "unknown" — a
        # 4-way softmax has no way to reject input it was never meant to type.
        self._n_out = len(self.classes) + (1 if self._trained else 0)
        model.classifier[-1] = torch.nn.Linear(in_features, self._n_out)

        if self._trained:
            state = torch.load(weights_path, map_location=self.device)
            model.load_state_dict(state)

        model.to(self.device).eval()
        return model

    def _classify(self, image: np.ndarray | None, source_path: str | None) -> TagResult:
        if image is None:
            return TagResult("unknown", 0.0)
        import cv2

        torch = self._torch
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        rgb = cv2.resize(rgb, (224, 224)).astype(np.float32) / 255.0
        for c in range(3):
            rgb[..., c] = (rgb[..., c] - _IMAGENET_MEAN[c]) / _IMAGENET_STD[c]
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)[0]
        idx = int(torch.argmax(probs).item())
        if not self._trained:
            # Untrained head: the argmax is noise. Return score 0.0 so the stage's
            # min_score gate coerces it to "unknown" instead of a confident guess.
            return TagResult(type="unknown", score=0.0)
        if idx >= len(self.classes):
            # The "other" bucket: not a clinical image. Report unknown with the
            # rejection confidence so the audit shows how sure the reject was.
            return TagResult(type="unknown", score=float(probs[idx].item()))
        return TagResult(type=self.classes[idx], score=float(probs[idx].item()))


register_adapter("mobilenetv3", lambda logical_name, spec, env: MobileNetV3Adapter(logical_name, spec, env))
