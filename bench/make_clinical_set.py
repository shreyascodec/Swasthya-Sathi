"""Generate a SYNTHETIC clinical-image set for the MedGemma image bench.

IMPORTANT — these are procedurally generated PLACEHOLDER images (colored shapes,
gradients, noise). They contain NO real pathology. They are enough to test:
  * plumbing (image -> MedGemma -> structured tag),
  * image-TYPE classification behavior (skin/eye/wound/oral/unknown),
  * quality-gate behavior (blurry / junk should be flagged unusable),
  * latency + VRAM on the 4060.
They are NOT enough to measure any clinical/diagnostic accuracy — there is no
ground-truth disease in a synthetic image. Any "assessment" the model produces on
these is ungrounded by construction. Swap in real, licensed, consented images
before trusting any diagnostic signal.

Run:  python -m bench.make_clinical_set
Writes: data/clinical/<class>/*.png  +  data/clinical/index.json
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "clinical"
INDEX = OUT_DIR / "index.json"
SIZE = (768, 768)
N_PER_CLASS = 3
SEED = 7


def _skin(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Flat-ish skin field: warm tone + gentle mottling (a plain patch of skin)."""
    base = rng.choice([(214, 168, 140), (188, 140, 112), (150, 104, 80)])
    draw.rectangle([0, 0, *SIZE], fill=base)
    for _ in range(500):
        x, y = rng.randint(0, SIZE[0]), rng.randint(0, SIZE[1])
        d = rng.randint(6, 22)
        shade = tuple(max(0, min(255, c + rng.randint(-18, 18))) for c in base)
        draw.ellipse([x, y, x + d, y + d], fill=shade)


def _wound(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Skin field with a red/dark irregular lesion (stands in for a wound)."""
    _skin(draw, rng)
    cx, cy = SIZE[0] // 2, SIZE[1] // 2
    pts = []
    for a in range(0, 360, 20):
        r = rng.randint(90, 170)
        pts.append((cx + int(r * math.cos(math.radians(a))),
                    cy + int(r * math.sin(math.radians(a)))))
    draw.polygon(pts, fill=(150, 30, 26))
    for _ in range(120):  # darker scabbing / exudate
        x = cx + rng.randint(-120, 120)
        y = cy + rng.randint(-120, 120)
        d = rng.randint(6, 26)
        draw.ellipse([x, y, x + d, y + d], fill=(90, 20, 18))


def _eye(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Eye-like target: sclera, iris, pupil, a couple of vessels."""
    draw.rectangle([0, 0, *SIZE], fill=(238, 232, 228))
    cx, cy = SIZE[0] // 2, SIZE[1] // 2
    draw.ellipse([cx - 300, cy - 150, cx + 300, cy + 150], fill=(248, 246, 244))
    iris = rng.choice([(84, 110, 140), (96, 74, 52), (72, 96, 72)])
    draw.ellipse([cx - 130, cy - 130, cx + 130, cy + 130], fill=iris)
    draw.ellipse([cx - 55, cy - 55, cx + 55, cy + 55], fill=(20, 20, 22))
    for _ in range(12):  # red vessels on the sclera
        x0 = cx + rng.choice([-1, 1]) * rng.randint(150, 280)
        y0 = cy + rng.randint(-60, 60)
        draw.line([x0, y0, x0 + rng.randint(-40, 40), y0 + rng.randint(-20, 20)],
                  fill=(200, 80, 80), width=2)


def _oral(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Mouth-like: pink mucosa with a lighter tooth row."""
    draw.rectangle([0, 0, *SIZE], fill=(190, 96, 104))
    draw.ellipse([120, 200, 648, 560], fill=(150, 54, 66))  # oral cavity
    for i in range(8):  # tooth row
        x = 180 + i * 55
        draw.rectangle([x, 230, x + 44, 300], fill=(236, 230, 214))
    for _ in range(200):  # mucosa texture
        x, y = rng.randint(0, SIZE[0]), rng.randint(0, SIZE[1])
        d = rng.randint(4, 14)
        draw.ellipse([x, y, x + d, y + d],
                     fill=(200 + rng.randint(-20, 20), 100, 108))


_RENDER = {"skin": _skin, "wound": _wound, "eye": _eye, "oral": _oral}


def _junk(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Not a clinical image at all: random color blocks (guardrail test)."""
    for _ in range(40):
        x0, y0 = rng.randint(0, SIZE[0]), rng.randint(0, SIZE[1])
        x1, y1 = rng.randint(0, SIZE[0]), rng.randint(0, SIZE[1])
        draw.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                       fill=tuple(rng.randint(0, 255) for _ in range(3)))


def build() -> list[dict]:
    rng = random.Random(SEED)
    items: list[dict] = []

    for cls, render in _RENDER.items():
        for k in range(N_PER_CLASS):
            img = Image.new("RGB", SIZE, "white")
            render(ImageDraw.Draw(img), rng)
            blurry = (k == N_PER_CLASS - 1)  # last one of each class = degraded
            if blurry:
                img = img.filter(ImageFilter.GaussianBlur(9))
            rel = f"{cls}/{cls}_{k}{'_blur' if blurry else ''}.png"
            path = OUT_DIR / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path)
            items.append({
                "path": rel,
                "intended_type": cls,
                "quality": "unusable" if blurry else "usable",
                "note": "synthetic placeholder — no real pathology",
            })

    # Two junk images: correct behavior is type=unknown / not-a-clinical-image.
    for k in range(2):
        img = Image.new("RGB", SIZE, "white")
        _junk(ImageDraw.Draw(img), rng)
        rel = f"junk/junk_{k}.png"
        path = OUT_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        items.append({"path": rel, "intended_type": "unknown",
                      "quality": "usable",
                      "note": "not a clinical image — guardrail test"})

    return items


def main() -> None:
    items = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps({"items": items, "synthetic": True}, indent=2),
                     encoding="utf-8")
    by = {}
    for it in items:
        by[it["intended_type"]] = by.get(it["intended_type"], 0) + 1
    print(f"Wrote {len(items)} synthetic clinical images {by} -> {OUT_DIR}")
    print("REMINDER: synthetic placeholders — no real pathology, no diagnostic signal.")


if __name__ == "__main__":
    main()
