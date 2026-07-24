"""Fine-tune the MobileNetV3 4-class image-tagging head (skin/eye/wound/oral).

    python -m bench.train_imagetag                 # train + eval + save
    python -m bench.train_imagetag --per-class 200 # bigger synthetic train set

WHAT THIS CHECKPOINT IS — AND IS NOT
------------------------------------
Training data is the SAME procedurally-generated synthetic set the bench uses
(bench/make_clinical_set.py): colored shapes, gradients and noise standing in for
skin/eye/wound/oral. There is no real pathology in any of it.

So the resulting checkpoint is:
  * a REAL, fast classifier over that synthetic distribution — enough to prove
    the plumbing, the latency, and the stage's min_score/quality gating, and
  * NOT a clinically validated tagger. Its accuracy on real patient photos is
    unknown and probably poor: it has learned "reddish disc on pale field" and
    similar shape cues, not anatomy.

Retrain on real, licensed, consented images before any clinical claim. The
training code below does not change when the data does — only the input folder.

Method: ImageNet-pretrained MobileNetV3-Small backbone (frozen) + a fresh head
trained on augmented synthetic crops. Freezing keeps the real ImageNet features
intact, which is what makes a tiny training set viable at all.

THE HEAD IS 5-WAY, NOT 4-WAY. A 4-way softmax must spread probability across the
four clinical classes, so it has no way to say "this isn't a clinical photo at
all" — measured, an untrained-negative model tagged a junk image `skin` at 0.609,
sailing past the stage's 0.5 gate. A fifth "other" class (junk renders, report
pages, flat/noise fields) gives the model somewhere to put non-clinical input.
The adapter maps that class to "unknown", so the four reported types are
unchanged and the no-diagnosis contract is untouched.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_WEIGHTS = ROOT / "models" / "weights" / "imagetag_mobilenet_v3s.pt"
EVAL_DIR = ROOT / "data" / "clinical"
PAGES_DIR = ROOT / "data" / "eval" / "pages"
CLASSES = ["skin", "eye", "wound", "oral"]
#: Trained head = CLASSES + a negative bucket. The adapter maps OTHER -> "unknown".
OTHER = "other"
TRAIN_CLASSES = CLASSES + [OTHER]

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _render_set(per_class: int, seed: int) -> list[tuple[Image.Image, int]]:
    """Generate synthetic training images using the bench's own renderers.

    Seeded differently from the eval set in data/clinical, so the 12 committed
    images stay a genuine held-out check rather than training data.
    """
    from bench.make_clinical_set import _RENDER, _junk, SIZE

    rng = random.Random(seed)
    samples: list[tuple[Image.Image, int]] = []
    for label, cls in enumerate(CLASSES):
        render = _RENDER[cls]
        for k in range(per_class):
            img = Image.new("RGB", SIZE, "white")
            render(ImageDraw.Draw(img), rng)
            if k % 5 == 4:                      # some blurred, as in the real set
                img = img.filter(ImageFilter.GaussianBlur(rng.uniform(2, 9)))
            samples.append((img, label))

    # Negative class: everything a kiosk camera/scanner sees that is NOT a
    # clinical close-up. Report pages matter most — the pipeline feeds scanned
    # pages through this stage, and they must not come back tagged "skin".
    other_label = TRAIN_CLASSES.index(OTHER)
    page_files = sorted(PAGES_DIR.glob("*.png")) if PAGES_DIR.exists() else []
    for k in range(per_class):
        mode = k % 3
        if mode == 0:                            # junk renders
            img = Image.new("RGB", SIZE, "white")
            _junk(ImageDraw.Draw(img), rng)
        elif mode == 1 and page_files:           # real scanned report pages
            img = Image.open(rng.choice(page_files)).convert("RGB").resize(SIZE)
        else:                                    # flat / noisy fields
            base = tuple(rng.randint(120, 255) for _ in range(3))
            img = Image.new("RGB", SIZE, base)
            arr = np.asarray(img).astype(np.int16)
            arr += rng.randint(4, 30) * np.random.randn(*arr.shape).astype(np.int16)
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        if k % 5 == 4:
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(2, 9)))
        samples.append((img, other_label))
    return samples


def _augment(img: Image.Image, rng: random.Random) -> Image.Image:
    """Light augmentation so the head keys on colour/texture, not framing."""
    if rng.random() < 0.5:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if rng.random() < 0.3:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if rng.random() < 0.5:
        img = img.rotate(rng.uniform(-25, 25), fillcolor=(255, 255, 255))
    if rng.random() < 0.4:
        w, h = img.size
        m = int(min(w, h) * rng.uniform(0.05, 0.20))
        img = img.crop((m, m, w - m, h - m))
    return img


def _to_tensor_batch(images: list[Image.Image], torch):
    arr = np.stack([
        (np.asarray(im.resize((224, 224)), dtype=np.float32) / 255.0
         - _IMAGENET_MEAN) / _IMAGENET_STD
        for im in images
    ]).transpose(0, 3, 1, 2)
    return torch.from_numpy(arr)


def _build_model(torch, torchvision, freeze: bool = True):
    from torchvision.models import MobileNet_V3_Small_Weights

    model = torchvision.models.mobilenet_v3_small(
        weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1
    )
    if freeze:
        for p in model.features.parameters():
            p.requires_grad = False
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = torch.nn.Linear(in_features, len(TRAIN_CLASSES))
    return model


def _evaluate(model, torch, device) -> tuple[float, list[str]]:
    """Score against held-out data: the committed clinical set (typed correctly)
    AND non-clinical input (junk + report pages), which must land in `other`."""
    index = json.loads((EVAL_DIR / "index.json").read_text(encoding="utf-8"))
    correct = total = 0
    notes: list[str] = []
    model.eval()

    def predict(path: Path) -> tuple[str, float]:
        img = Image.open(path).convert("RGB")
        with torch.no_grad():
            probs = torch.softmax(model(_to_tensor_batch([img], torch).to(device)), 1)[0]
        i = int(torch.argmax(probs).item())
        return TRAIN_CLASSES[i], float(probs[i])

    for item in index["items"]:
        want = item["intended_type"] if item["intended_type"] in CLASSES else OTHER
        got, score = predict(EVAL_DIR / item["path"])
        ok = got == want
        correct += ok
        total += 1
        notes.append(f"  {item['path']:24s} -> {got:6s} ({score:.2f}) "
                     f"{'OK' if ok else 'WRONG, want ' + want}")

    # Guardrail: scanned report pages must never be typed as a clinical image.
    for page in sorted(PAGES_DIR.glob("*.png"))[:3] if PAGES_DIR.exists() else []:
        got, score = predict(page)
        ok = got == OTHER
        correct += ok
        total += 1
        notes.append(f"  pages/{page.name:18s} -> {got:6s} ({score:.2f}) "
                     f"{'OK' if ok else 'WRONG, want ' + OTHER}")

    return (correct / total if total else 0.0), notes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=160)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=20260720)
    args = ap.parse_args()

    import torch
    import torchvision

    device = "cuda" if torch.cuda.is_available() else "cpu"
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    print(f"Generating {args.per_class}/class synthetic training images "
          f"(seed {args.seed}, held-out eval = data/clinical) ...")
    samples = _render_set(args.per_class, args.seed)
    print(f"  {len(samples)} training images, device={device}")

    model = _build_model(torch, torchvision).to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr)
    lossf = torch.nn.CrossEntropyLoss()

    for epoch in range(1, args.epochs + 1):
        model.train()
        rng.shuffle(samples)
        total_loss = seen = hits = 0
        for i in range(0, len(samples), args.batch):
            chunk = samples[i:i + args.batch]
            imgs = [_augment(im, rng) for im, _ in chunk]
            labels = torch.tensor([lb for _, lb in chunk], device=device)
            x = _to_tensor_batch(imgs, torch).to(device)
            opt.zero_grad()
            out = model(x)
            loss = lossf(out, labels)
            loss.backward()
            opt.step()
            total_loss += float(loss) * len(chunk)
            hits += int((out.argmax(1) == labels).sum())
            seen += len(chunk)
        print(f"  epoch {epoch:2d}/{args.epochs}  loss {total_loss/seen:.4f}  "
              f"train_acc {hits/seen:.3f}")

    acc, notes = _evaluate(model, torch, device)
    print(f"\nHeld-out eval on data/clinical: {acc:.2%}")
    for n in notes:
        print(n)

    OUT_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), OUT_WEIGHTS)
    print(f"\nSaved -> {OUT_WEIGHTS}")
    print("REMINDER: trained on SYNTHETIC placeholders. Not clinically validated; "
          "retrain on real consented images before any clinical claim.")


if __name__ == "__main__":
    main()
