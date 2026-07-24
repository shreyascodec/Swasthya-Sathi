"""[3] Image Tagging.

Tags clinical images by TYPE (skin/eye/wound/oral) + a quality flag, and nothing
more. Explicitly type/quality only — NEVER a diagnosis (product invariant). Type
comes from the configured tagger via ModelManager; quality is reused from the
Phase-1 gate, not decided by the model. Low-confidence or unknown types fall back
to "unknown" rather than guessing.

Swap tagger by editing image_tag.primary.impl in config/models.yaml.

Tested/won/open: tagging, class enforcement, quality reuse, no-diagnosis schema,
graceful stub fallback and load/unload verified. Open: a fine-tuned MobileNetV3
checkpoint (predictions are only meaningful once trained weights are supplied).
"""

from __future__ import annotations

import cv2

from core.context import ImageTag, SessionContext
from core.stage import Stage
from models.imagetag_base import DEFAULT_CLASSES

_ALLOWED = set(DEFAULT_CLASSES) | {"unknown"}


class ImageTagStage(Stage):
    name = "image_tag"
    order = 3
    description = "Tag clinical images by type + quality (never diagnosis)."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._tagger = None
        self._active_impl: str | None = None

    def _configured_impl(self) -> str:
        return self.config.models.get("image_tag", {}).get("primary", {}).get("impl", "stub_imagetag")

    def _classes(self) -> list[str]:
        return self.config.models.get("image_tag", {}).get("primary", {}).get("classes", DEFAULT_CLASSES)

    def _min_score(self) -> float:
        return float(self.config.stage_cfg("image_tag").get("min_score_for_type", 0.5))

    def load(self) -> None:
        """DEFERRED — see ``_ensure_tagger``.

        ``Stage.__call__`` loads before it can see the context, but the kiosk's
        normal input is lab-report pages only, and those are all skipped in
        ``run``. Eagerly loading here cost ~17 s (torch + CUDA init) to tag zero
        images on every ordinary session. The real load is deferred to the first
        upload that actually needs tagging; ``unload`` stays safe because
        ``ModelManager.release`` is a no-op when nothing was loaded.
        """
        return None

    def _ensure_tagger(self) -> None:
        if self._tagger is not None:
            return
        try:
            self._tagger = self.models.get("image_tag")
            self._active_impl = self._configured_impl()
        except ImportError:
            # Graceful degradation to the stub tagger (no torch / reduced mode).
            from models.imagetag_stub import StubImageTagAdapter

            self.models.release("image_tag")
            self._tagger = self.models.get(
                "image_tag",
                factory=lambda logical_name, spec, env: StubImageTagAdapter(
                    logical_name, {**spec, "device": "cpu"}, env
                ),
            )
            self._active_impl = f"{self._configured_impl()}->stub_imagetag(fallback)"

    def unload(self) -> None:
        self.models.release("image_tag")
        self._tagger = None

    def run(self, ctx: SessionContext) -> SessionContext:
        allowed = set(self._classes()) | {"unknown"}
        min_score = self._min_score()

        tags: list[ImageTag] = []
        skipped_docs = 0
        for upload in ctx.uploads:
            # Only CLINICAL PHOTOS are tagged (skin/eye/wound/oral). Report scans
            # and PDFs are text documents — they belong to OCR, not tagging, and
            # tagging them yields a meaningless "unknown" (the reported bug: 3
            # lab-report pages all tagged "unknown · score 1").
            #
            # `is_document` is decided at intake: PDFs are always documents, and
            # image pages pass through a white-ratio gate (a lab report is mostly
            # white text on white -> document). A genuine clinical photo is
            # is_document False (or None for hand-built contexts) and is tagged.
            if upload.type != "image":
                continue
            if upload.is_document:
                skipped_docs += 1
                continue

            # First taggable image — only now is the model worth its load cost.
            self._ensure_tagger()

            img_path = upload.processed_path or upload.path
            image = cv2.imread(img_path) if img_path else None
            res = self._tagger.classify(image, source_path=upload.source_path)

            # Enforce type/quality only: coerce unknown/off-list/low-score types.
            tag_type = res.type if (res.type in allowed and res.score >= min_score) else "unknown"
            if tag_type not in _ALLOWED and tag_type not in allowed:
                tag_type = "unknown"

            quality_ok = upload.quality_ok if upload.quality_ok is not None else (not upload.needs_rescan)

            tags.append(
                ImageTag(
                    upload_id=upload.id,
                    type=tag_type if tag_type in _ALLOWED else "unknown",
                    quality_ok=bool(quality_ok),
                    score=round(res.score, 3),
                )
            )

        ctx.image_tags = tags
        by_type = {t: sum(1 for x in tags if x.type == t) for t in allowed}
        impl = self._active_impl or "not-loaded(no clinical images)"
        ctx.log(
            "stage.image_tag.done",
            detail=(f"impl={impl} tagged={len(tags)} "
                    f"skipped_docs={skipped_docs} types={by_type}"),
        )
        return ctx
