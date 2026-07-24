"""Phase 1 acceptance tests (PLAN.md Phase 1).

Acceptance: upload 5 mixed-quality report photos; blurry/badly-lit ones flagged
for rescan; clean ones stored with a hash; preprocessed artifacts produced.
No GPU. Uses synthetic images (sharp / blurry / dark) + a generated PDF.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.context import SessionContext, UploadedFile
from core.pipeline import Pipeline
from stages.imaging import IntakeParams, quality_metrics


# --- synthetic image builders ------------------------------------------------
def _sharp(h: int = 1200, w: int = 900) -> np.ndarray:
    """High-frequency checkerboard -> high Laplacian variance, mid brightness."""
    img = np.full((h, w), 150, dtype=np.uint8)
    block = 10
    ys, xs = np.indices((h, w))
    checker = (((ys // block) + (xs // block)) % 2).astype(bool)
    img[checker] = 60
    img[~checker] = 230
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _blurry() -> np.ndarray:
    return cv2.GaussianBlur(_sharp(), (25, 25), 0)


def _dark() -> np.ndarray:
    return (_sharp().astype(np.float32) * 0.12).astype(np.uint8)


def _write(img: np.ndarray, path: Path) -> Path:
    cv2.imwrite(str(path), img)
    return path


def _pipeline(tmp_path: Path) -> Pipeline:
    p = Pipeline(env_name="dev_4060")
    p.config.env.data_dir = str(tmp_path / "session_data")  # isolate test artifacts
    return p


def _ctx_with(files: list[tuple[str, str]]) -> SessionContext:
    ctx = SessionContext(session_id="phase1test01", lang="hi")
    for i, (path, ftype) in enumerate(files):
        ctx.uploads.append(
            UploadedFile(id=f"u{i}", path=path, source_path=path, type=ftype)
        )
    return ctx


# --- quality gate (pure) -----------------------------------------------------
def _text_page(rotate_deg: float = 0.0) -> np.ndarray:
    """A white page of evenly spaced dark text lines, optionally rotated."""
    img = np.full((900, 700, 3), 255, dtype=np.uint8)
    for y in range(90, 820, 46):                 # 'text' lines
        cv2.rectangle(img, (70, y), (630, y + 16), (30, 30, 30), -1)
    if rotate_deg:
        h, w = img.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rotate_deg, 1.0)
        img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    return img


def test_skew_estimate_is_zero_on_a_straight_page() -> None:
    """A straight page must not be rotated.

    The previous minAreaRect estimator measured the ink cloud's bounding box, not
    text baselines: on a straight render of a real lab report it returned 4.87 deg.
    Rotating by that displaced rows ~140 px across the page, so an analyte's name
    and its value landed on different OCR rows — extraction recall fell to 12%.
    """
    from stages.imaging import estimate_skew_angle

    assert abs(estimate_skew_angle(_text_page(), 15.0)) < 0.5


def test_skew_estimate_recovers_known_rotation() -> None:
    from stages.imaging import estimate_skew_angle

    for injected in (-3.0, -1.0, 2.0, 5.0):
        est = estimate_skew_angle(_text_page(injected), 15.0)
        # deskew() applies +est, so it must counter the injected rotation.
        assert abs(est + injected) < 0.6, f"{injected=} {est=}"


def test_ocr_punctuation_normalization() -> None:
    """OCR emits fullwidth look-alikes. A single fullwidth colon in
    'Serum Chlorides : 103.7 mEq/L' cost a real lab value."""
    from stages.ocr_extract import extract_fields, normalize_ocr_punctuation

    assert normalize_ocr_punctuation("Serum Chlorides ： 103.7") == "Serum Chlorides : 103.7"
    fields = extract_fields("Serum Chlorides ： 103.7 mEq/L 97-108 mEq/L", [], 0.8)
    assert any(f.name.startswith("Serum Chlorides") and f.value == "103.7" for f in fields)


def test_quality_gate_flags_blur_and_darkness() -> None:
    params = IntakeParams()
    assert quality_metrics(_sharp(), params).needs_rescan is False
    assert "blurry" in quality_metrics(_blurry(), params).reasons
    assert "too_dark" in quality_metrics(_dark(), params).reasons


# --- end-to-end: 5 mixed-quality photos --------------------------------------
def test_intake_five_mixed_quality(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    files = [
        (str(_write(_sharp(), raw / "clean1.png")), "image"),
        (str(_write(_sharp(), raw / "clean2.png")), "image"),
        (str(_write(_blurry(), raw / "blurry.png")), "image"),
        (str(_write(_dark(), raw / "dark.png")), "image"),
        (str(_write(_sharp(), raw / "clean3.png")), "image"),
    ]
    pipeline = _pipeline(tmp_path)
    ctx = _ctx_with(files)

    ctx = pipeline.run_stage("intake", ctx)

    assert len(ctx.uploads) == 5
    rescans = [u for u in ctx.uploads if u.needs_rescan]
    cleans = [u for u in ctx.uploads if not u.needs_rescan]
    assert len(rescans) == 2   # blurry + dark
    assert len(cleans) == 3    # three sharp

    for u in ctx.uploads:
        assert u.sha256 and len(u.sha256) == 64
        assert u.processed_path and Path(u.processed_path).exists()
        assert u.blur_score is not None and u.brightness is not None

    assert any(e.action == "stage.intake.done" for e in ctx.audit)


def test_compress_then_hash_matches_stored_bytes(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    files = [(str(_write(_sharp(), raw / "clean.png")), "image")]
    pipeline = _pipeline(tmp_path)
    ctx = pipeline.run_stage("intake", _ctx_with(files))

    up = ctx.uploads[0]
    stored = Path(up.processed_path).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == up.sha256


def test_intake_is_idempotent(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    files = [(str(_write(_sharp(), raw / "clean.png")), "image")]
    pipeline = _pipeline(tmp_path)

    ctx = pipeline.run_stage("intake", _ctx_with(files))
    first_hash = ctx.uploads[0].sha256
    ctx = pipeline.run_stage("intake", ctx)  # run again
    assert len(ctx.uploads) == 1
    assert ctx.uploads[0].sha256 == first_hash


# --- PDF intake --------------------------------------------------------------
def test_intake_renders_pdf_pages(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")  # PyMuPDF
    pdf_path = tmp_path / "report.pdf"
    doc = fitz.open()
    for n in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Lab report page {n} — Hemoglobin 13.5 g/dL")
    doc.save(str(pdf_path))
    doc.close()

    pipeline = _pipeline(tmp_path)
    ctx = pipeline.run_stage("intake", _ctx_with([(str(pdf_path), "pdf")]))

    assert len(ctx.uploads) == 2  # one processed page per PDF page
    for u in ctx.uploads:
        assert u.type == "pdf"
        assert Path(u.processed_path).exists()
