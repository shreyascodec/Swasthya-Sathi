"""Phase 3 acceptance tests (PLAN.md Phase 3).

Tags clinical images by type + quality with confidence; poor images flagged;
output carries no diagnostic language (schema restricts type to the 4 classes +
unknown). Verified via the stub tagger; the real MobileNetV3 path needs a
fine-tuned checkpoint. Also checks class/score enforcement, quality reuse from
Phase 1, graceful fallback, and load/unload.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

import models  # noqa: F401  (register adapters)
from core.context import SessionContext, UploadedFile
from core.pipeline import Pipeline

_ALLOWED = {"skin", "eye", "wound", "oral", "unknown"}


def _png(path: Path) -> str:
    cv2.imwrite(str(path), np.full((64, 64, 3), 127, dtype=np.uint8))
    return str(path)


def _sidecar(img_path: str, type_: str, score: float) -> None:
    Path(img_path + ".tag.json").write_text(
        json.dumps({"type": type_, "score": score}), encoding="utf-8"
    )


def _stub_pipeline() -> Pipeline:
    p = Pipeline(env_name="dev_4060")
    p.config.models["image_tag"]["primary"]["impl"] = "stub_imagetag"
    p.config.models["image_tag"]["primary"]["device"] = "cpu"
    return p


def _ctx_with(upload: UploadedFile) -> SessionContext:
    ctx = SessionContext(session_id="p3test", lang="hi")
    ctx.uploads.append(upload)
    return ctx


def test_stub_tags_by_type_with_score(tmp_path: Path) -> None:
    img = _png(tmp_path / "skin1.png")
    _sidecar(img, "skin", 0.92)
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img,
                      type="image", quality_ok=True)
    pipeline = _stub_pipeline()

    ctx = pipeline.run_stage("image_tag", _ctx_with(up))

    assert len(ctx.image_tags) == 1
    tag = ctx.image_tags[0]
    assert tag.type == "skin"
    assert tag.score == 0.92
    assert tag.quality_ok is True
    assert "image_tag" not in pipeline.models.loaded  # unloaded on exit


def test_offlist_type_becomes_unknown(tmp_path: Path) -> None:
    img = _png(tmp_path / "x.png")
    _sidecar(img, "melanoma", 0.99)   # not a valid class; must not leak through
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img, type="image")
    ctx = _stub_pipeline().run_stage("image_tag", _ctx_with(up))
    assert ctx.image_tags[0].type == "unknown"


def test_low_score_becomes_unknown(tmp_path: Path) -> None:
    img = _png(tmp_path / "y.png")
    _sidecar(img, "eye", 0.20)        # below min_score_for_type (0.5)
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img, type="image")
    ctx = _stub_pipeline().run_stage("image_tag", _ctx_with(up))
    assert ctx.image_tags[0].type == "unknown"


def test_quality_flag_reused_from_phase1(tmp_path: Path) -> None:
    img = _png(tmp_path / "wound.png")
    _sidecar(img, "wound", 0.88)
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img,
                      type="image", quality_ok=False, needs_rescan=True)
    ctx = _stub_pipeline().run_stage("image_tag", _ctx_with(up))
    assert ctx.image_tags[0].type == "wound"
    assert ctx.image_tags[0].quality_ok is False


def test_no_diagnostic_language_only_types(tmp_path: Path) -> None:
    img = _png(tmp_path / "z.png")
    _sidecar(img, "oral", 0.75)
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img, type="image")
    ctx = _stub_pipeline().run_stage("image_tag", _ctx_with(up))
    assert ctx.image_tags[0].type in _ALLOWED


def test_pdf_uploads_are_skipped(tmp_path: Path) -> None:
    up = UploadedFile(id="u0", path=str(tmp_path / "r.pdf"), source_path=str(tmp_path / "r.pdf"),
                      type="pdf")
    ctx = _stub_pipeline().run_stage("image_tag", _ctx_with(up))
    assert ctx.image_tags == []


def test_default_tagger_completes_or_falls_back(tmp_path: Path) -> None:
    """With default impl=mobilenetv3: runs if torch present, else falls back to
    stub. Either way it must complete, stay within the allowed classes, and
    release the model."""
    img = _png(tmp_path / "img.png")
    up = UploadedFile(id="u0", path=img, source_path=img, processed_path=img, type="image")
    pipeline = Pipeline(env_name="dev_4060")  # default config (mobilenetv3 primary)

    ctx = pipeline.run_stage("image_tag", _ctx_with(up))

    assert len(ctx.image_tags) == 1
    assert ctx.image_tags[0].type in _ALLOWED
    assert "image_tag" not in pipeline.models.loaded
    assert any(e.action == "stage.image_tag.done" for e in ctx.audit)


def test_report_documents_are_not_tagged(tmp_path: Path) -> None:
    """A lab-report scan (is_document=True) must NOT be image-tagged.

    Regression: report pages are type='image' and slipped past the old
    `type != image` skip, getting a meaningless 'unknown · score 1' tag. Only
    clinical photos (is_document falsy) should be tagged.
    """
    report = _png(tmp_path / "report_p1.png")
    _sidecar(report, "skin", 0.99)   # even if the model would guess, it's a document
    doc = UploadedFile(id="doc", path=report, source_path=report, processed_path=report,
                       type="image", is_document=True)
    photo = _png(tmp_path / "skin.png")
    _sidecar(photo, "skin", 0.91)
    clinical = UploadedFile(id="pic", path=photo, source_path=photo, processed_path=photo,
                            type="image", is_document=False)

    ctx = SessionContext(session_id="p3doc", lang="hi")
    ctx.uploads.extend([doc, clinical])
    ctx = _stub_pipeline().run_stage("image_tag", ctx)

    tagged_ids = {t.upload_id for t in ctx.image_tags}
    assert "doc" not in tagged_ids, "report document was wrongly tagged"
    assert "pic" in tagged_ids, "clinical photo should be tagged"
    assert len(ctx.image_tags) == 1
    assert any(e.detail and "skipped_docs=1" in e.detail
               for e in ctx.audit if e.action == "stage.image_tag.done")
