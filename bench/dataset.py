"""Eval-set loader for the summary bake-off."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.context import OCRField

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "eval_set.json"


@dataclass
class EvalItem:
    id: str
    lang: str
    ocr_fields: list[OCRField]
    gold: dict
    page_images: list[str] = None          # absolute paths to page PNGs (multi/multimodal)
    n_pages: int = 1

    def __post_init__(self):
        if self.page_images is None:
            self.page_images = []


def load_eval_set(path: str | Path = DEFAULT_PATH) -> list[EvalItem]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Eval set missing: {path}. Generate it with "
            f"`python -m bench.make_eval_set`."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[EvalItem] = []
    for raw in data.get("items", []):
        fields = [
            OCRField(
                name=f["name"], value=str(f["value"]), unit=f.get("unit"),
                low_confidence=bool(f.get("low_confidence", False)),
            )
            for f in raw.get("ocr_fields", [])
        ]
        base_dir = path.resolve().parent.parent.parent  # repo root (data/eval/..)
        page_images = [
            str((base_dir / p).resolve()) for p in raw.get("page_images", [])
        ]
        items.append(EvalItem(
            id=raw["id"], lang=raw.get("lang", "en"),
            ocr_fields=fields, gold=raw.get("gold", {}),
            page_images=page_images,
            n_pages=int(raw.get("n_pages", 1)),
        ))
    return items
