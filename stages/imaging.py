"""Classical-CV helpers for Stage [1] Intake & Preprocess.

Pure, model-free functions so they can be unit-tested with synthetic images and
reused by the Streamlit page. No GPU, offline. All tunables come from the stage
config block (config/stages.yaml), never hardcoded.

Pipeline per page:  read -> deskew -> denoise -> DPI/size normalize ->
                    quality gate (blur + brightness) -> compress-then-hash-store.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class IntakeParams:
    """Resolved Stage-1 tunables (from config/stages.yaml 'intake')."""

    storage_subdir: str = "uploads"
    pdf_render_dpi: int = 200
    target_long_edge_px: int = 2000
    deskew_max_angle_deg: float = 15.0
    denoise_h: int = 7
    jpeg_quality: int = 85
    blur_laplacian_min: float = 100.0
    brightness_min: float = 40.0
    brightness_max: float = 220.0
    doc_white_thresh: int = 180
    doc_min_white_ratio: float = 0.35
    extract_text_layer: bool = True
    text_layer_min_words: int = 20

    @classmethod
    def from_cfg(cls, cfg: dict) -> "IntakeParams":
        gate = cfg.get("quality_gate", {})
        doc_gate = cfg.get("document_gate", {})
        text_layer = cfg.get("text_layer", {})
        return cls(
            storage_subdir=cfg.get("storage_subdir", "uploads"),
            pdf_render_dpi=int(cfg.get("pdf_render_dpi", 200)),
            target_long_edge_px=int(cfg.get("target_long_edge_px", 2000)),
            deskew_max_angle_deg=float(cfg.get("deskew_max_angle_deg", 15.0)),
            denoise_h=int(cfg.get("denoise_h", 7)),
            jpeg_quality=int(cfg.get("jpeg_quality", 85)),
            blur_laplacian_min=float(gate.get("blur_laplacian_min", 100.0)),
            brightness_min=float(gate.get("brightness_min", 40.0)),
            brightness_max=float(gate.get("brightness_max", 220.0)),
            doc_white_thresh=int(doc_gate.get("white_thresh", 180)),
            doc_min_white_ratio=float(doc_gate.get("min_white_ratio", 0.35)),
            extract_text_layer=bool(text_layer.get("enabled", True)),
            text_layer_min_words=int(text_layer.get("min_words", 20)),
        )


@dataclass
class QualityResult:
    blur_score: float
    brightness: float
    needs_rescan: bool
    reasons: list[str] = field(default_factory=list)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def guess_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "unknown"


# --- reading -----------------------------------------------------------------
def read_pages(path: str | Path, file_type: str, params: IntakeParams) -> list[np.ndarray]:
    """Return one BGR ndarray per page. Images -> 1 page; PDFs -> N pages."""
    path = Path(path)
    if file_type == "pdf":
        return _render_pdf(path, params.pdf_render_dpi)
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return [img]


def _render_pdf(path: Path, dpi: int) -> list[np.ndarray]:
    try:
        import fitz  # PyMuPDF; ARM-compatible, no external poppler dependency
    except ImportError as exc:  # pragma: no cover - env dependent
        raise ImportError(
            "PDF intake needs PyMuPDF. Install it: pip install PyMuPDF"
        ) from exc

    pages: list[np.ndarray] = []
    zoom = dpi / 72.0  # PDF user-space is 72 dpi
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(str(path)) as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return pages


# --- preprocessing -----------------------------------------------------------
def estimate_skew_angle(img: np.ndarray, max_angle: float, step: float = 0.25) -> float:
    """Estimate document skew (deg) by horizontal-projection profile.

    For each candidate angle the ink is rotated and summed into row totals. When
    text lines are level, rows alternate between dense (a line) and empty (the
    gap), so the VARIANCE of that profile peaks. The angle maximizing it is the
    skew.

    Replaces a ``cv2.minAreaRect`` estimate over all ink pixels, which measured
    the bounding box of the ink cloud — a quantity with no relationship to text
    baselines. On a perfectly straight digital render of a real lab report it
    returned **4.87 deg**, and rotating by that displaced rows ~140 px across the
    page, so an analyte's name and its value landed on different reconstructed
    rows. OCR extraction recall on that page was 12%.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    if int((thresh > 0).sum()) < 50:          # too little ink to judge
        return 0.0

    # Work small: skew is a global property and this is an O(angles) search.
    h, w = thresh.shape
    scale = min(1.0, 800.0 / max(h, w))
    if scale < 1.0:
        thresh = cv2.resize(thresh, (max(int(w * scale), 1), max(int(h * scale), 1)),
                            interpolation=cv2.INTER_AREA)
    small_h, small_w = thresh.shape
    center = (small_w / 2, small_h / 2)

    def score(angle: float) -> float:
        if angle == 0.0:
            rot = thresh
        else:
            m = cv2.getRotationMatrix2D(center, angle, 1.0)
            rot = cv2.warpAffine(thresh, m, (small_w, small_h),
                                 flags=cv2.INTER_NEAREST, borderValue=0)
        profile = rot.sum(axis=1, dtype=np.float64)
        return float(profile.var())

    limit = abs(float(max_angle))
    best_angle, best_score = 0.0, score(0.0)
    n = int(limit / step)
    for i in range(1, n + 1):
        for cand in (i * step, -i * step):
            s = score(cand)
            if s > best_score:
                best_angle, best_score = cand, s
    return float(best_angle)


def deskew(img: np.ndarray, params: IntakeParams) -> np.ndarray:
    angle = estimate_skew_angle(img, params.deskew_max_angle_deg)
    if abs(angle) < 0.1:
        return img
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def denoise(img: np.ndarray, params: IntakeParams) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(img, None, params.denoise_h, params.denoise_h, 7, 21)


def normalize_size(img: np.ndarray, params: IntakeParams) -> np.ndarray:
    """Normalize the longest edge to target_long_edge_px (approx DPI-normalize)."""
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge == 0:
        return img
    scale = params.target_long_edge_px / long_edge
    if abs(scale - 1.0) < 0.02:
        return img
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (max(int(w * scale), 1), max(int(h * scale), 1)), interpolation=interp)


def preprocess(img: np.ndarray, params: IntakeParams) -> np.ndarray:
    """deskew -> denoise -> size/DPI normalize."""
    return normalize_size(denoise(deskew(img, params), params), params)


# --- OCR-routing hints ---------------------------------------------------------
def looks_like_document(img: np.ndarray, params: IntakeParams) -> bool:
    """Doc-vs-photo gate: printed reports are mostly near-white paper; clinical
    photos (skin/eye/wound/oral) are not. Lets OCR skip photo pages entirely."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white_ratio = float((gray >= params.doc_white_thresh).mean())
    return white_ratio >= params.doc_min_white_ratio


def pdf_text_layers(path: str | Path, min_words: int = 20) -> list["str | None"]:
    """Per-page embedded text layer for digital PDFs, or None per scanned page.

    A page with a real text layer needs no OCR at all — the extracted text is
    both faster (~0 s vs ~20 s/page on CPU) and more accurate than recognition.
    ``min_words`` guards against scanned PDFs that carry a few stray characters.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover - env dependent
        return []
    layers: list[str | None] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            words = page.get_text("words")
            layers.append(page.get_text("text") if len(words) >= min_words else None)
    return layers


# --- quality gate ------------------------------------------------------------
def quality_metrics(img: np.ndarray, params: IntakeParams) -> QualityResult:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())

    reasons: list[str] = []
    if blur_score < params.blur_laplacian_min:
        reasons.append("blurry")
    if brightness < params.brightness_min:
        reasons.append("too_dark")
    elif brightness > params.brightness_max:
        reasons.append("too_bright")

    return QualityResult(
        blur_score=blur_score,
        brightness=brightness,
        needs_rescan=bool(reasons),
        reasons=reasons,
    )


# --- compress-then-hash-then-store -------------------------------------------
def encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def store_image(img: np.ndarray, out_dir: str | Path, name: str, params: IntakeParams) -> tuple[str, str]:
    """Compress THEN hash THEN store. Returns (path, sha256).

    Hash is computed over the exact stored bytes (same lesson as Dakhla).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = encode_jpeg(img, params.jpeg_quality)
    sha256 = hashlib.sha256(data).hexdigest()
    out_path = out_dir / f"{name}.jpg"
    out_path.write_bytes(data)
    return str(out_path), sha256
