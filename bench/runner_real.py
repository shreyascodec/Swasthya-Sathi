"""Bench the pipeline against REAL lab reports (not the synthetic eval set).

    python -m bench.runner_real --pdfs <a.pdf> <b.pdf> ...
    python -m bench.runner_real --pdfs <a.pdf> --force-ocr   # exercise the OCR ENGINE

Everything else in bench/ runs on procedurally generated pages. This runner is
the first measurement against genuine Indian lab PDFs, which matters because the
real ones differ structurally from the synthetic set in ways that broke
extraction outright: real reports lay a table out ONE CELL PER LINE
(analyte / ':' / value / unit / range) rather than one row per line.

Ground truth is derived from the PDF's own embedded text layer by an independent
scan (label line, ':' line, numeric line) — deliberately NOT the pipeline's own
parser, so recall is measured against the document rather than against ourselves.
Values are compared numerically, so "1.40" and "1.4" agree.

``--force-ocr`` renders each page to a PNG and submits it as an IMAGE, so the
text-layer fast path cannot engage and the real OCR engine runs. This is the only
way to measure the deck's ">=90% OCR accuracy on printed reports" metric on the
engine itself: a digital PDF otherwise bypasses OCR entirely. Ground truth still
comes from the same PDF's text layer, which makes it exact — the rendered image
and the truth are two views of one document.

Writes bench/results_real/{latest_real.json, REPORT_REAL.md}.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "bench" / "results_real"
NUM_RE = re.compile(r"^\s*[\d.]+\s*$")
_NON_ANALYTE = {"doctor", "facility", "date", "drug"}


def ground_truth(pdf: Path) -> list[tuple[str, str]]:
    """(analyte, value) pairs read straight from the PDF text layer."""
    import fitz

    with fitz.open(str(pdf)) as doc:
        lines = "\n".join(p.get_text("text") for p in doc).splitlines()
    out: list[tuple[str, str]] = []
    for i in range(len(lines) - 2):
        if lines[i + 1].strip() == ":" and NUM_RE.match(lines[i + 2]):
            label = lines[i].strip()
            if label and label.lower() not in ("sample type", "test", "result"):
                out.append((label, lines[i + 2].strip()))
    return out


def _num(v: str) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _key(name: str) -> str:
    """Alphanumeric-only name key.

    OCR legitimately varies spacing and punctuation around the same analyte
    ("Estimated Average Glucose (eAG)" vs "...Glucose(eAG)"). Comparing raw
    strings scored a correctly-read value as a miss, which measures our matcher
    rather than the pipeline.
    """
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _name_matches(tname: str, gname: str) -> bool:
    t, g = _key(tname), _key(gname)
    return bool(t) and bool(g) and (t == g or t in g or g in t)


def _best_match(tname: str, got: dict[str, str]) -> tuple[str, str] | None:
    """Best-matching extracted field for a truth name, or None.

    Substring matching alone picks the FIRST candidate, which collides badly on
    real panels: "LDL" matches "VLDL", "Direct Bilirubin" matches "Indirect
    Bilirubin", "Creatinine" matches "CREATININE,URINE". Each collision scored a
    correctly-extracted value as a misread. Prefer an exact key match, then the
    candidate whose name length is closest to the truth's.
    """
    t = _key(tname)
    cands = [(g, v) for g, v in got.items() if _name_matches(tname, g)]
    if not cands:
        return None
    for g, v in cands:                       # exact key wins outright
        if _key(g) == t:
            return (g, v)
    return min(cands, key=lambda gv: abs(len(_key(gv[0])) - len(t)))


def _matches(truth: tuple[str, str], got: dict[str, str]) -> bool:
    """A truth pair is found if the best name-matching field carries its value."""
    tval = _num(truth[1])
    best = _best_match(truth[0], got)
    if best is None or tval is None:
        return False
    gval = _num(best[1])
    return gval is not None and abs(gval - tval) < 1e-9


def render_pages_as_images(pdf: Path, out_dir: Path, dpi: int = 200) -> list[Path]:
    """Rasterize each PDF page to a PNG — what a scanner/camera would hand us.

    Submitting these as images forces the OCR engine to run: the intake
    text-layer extractor only looks at PDFs, so a rendered page carries no text
    layer and cannot take the fast path.
    """
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    zoom = dpi / 72.0
    with fitz.open(str(pdf)) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            p = out_dir / f"{pdf.stem}_p{i}.png"
            pix.save(str(p))
            paths.append(p)
    return paths


def run_one(pdf: Path, pipeline, stage_names: list[str],
            force_ocr: bool = False, render_dpi: int = 200) -> dict:
    from core.context import UploadedFile
    from core.pipeline import new_session

    ctx = new_session(lang="hi")
    if force_ocr:
        img_dir = ROOT / "bench" / "results_real" / "_rendered" / pdf.stem
        for i, img in enumerate(render_pages_as_images(pdf, img_dir, render_dpi)):
            ctx.uploads.append(UploadedFile(id=f"{pdf.stem}_p{i}", path=str(img),
                                            type="image", source_path=str(img)))
    else:
        ctx.uploads.append(UploadedFile(id=pdf.stem, path=str(pdf),
                                        type="pdf", source_path=str(pdf)))
    timings: dict[str, float] = {}
    error = None
    for name in stage_names:
        t0 = time.perf_counter()
        try:
            ctx = pipeline.run_stage(name, ctx)
        except Exception as exc:                      # keep going; record it
            error = f"{name}: {type(exc).__name__}: {exc}"
            timings[name] = time.perf_counter() - t0
            break
        timings[name] = time.perf_counter() - t0

    truth = ground_truth(pdf)
    fields = ctx.ocr.fields if ctx.ocr else []
    got = {f.name: f.value for f in fields
           if not f.name.endswith("ref-range") and f.name not in _NON_ANALYTE}
    hits = [t for t in truth if _matches(t, got)]
    missed = [t for t in truth if t not in hits]

    # Value-level accuracy: an analyte found under the right name but with a
    # MISREAD digit still counts as recall, and on the OCR path that is exactly
    # the failure that matters clinically. Score name-matched pairs separately.
    name_matched, value_correct, misreads = 0, 0, []
    for tname, tval in truth:
        best = _best_match(tname, got)
        if best is None:
            continue
        gname, gval = best
        name_matched += 1
        if _num(tval) is not None and _num(gval) is not None and \
                abs(_num(gval) - _num(tval)) < 1e-9:
            value_correct += 1
        else:
            misreads.append((tname, tval, gval))

    findings = (ctx.summary.content.get("lab_findings") or []) if ctx.summary else []
    audit = {e.action: e.detail for e in ctx.audit}
    return {
        "pdf": pdf.name,
        "pages": len(ctx.uploads),
        "truth_values": len(truth),
        "extracted_values": len(got),
        "recall": (len(hits) / len(truth)) if truth else None,
        "name_matched": name_matched,
        "value_correct": value_correct,
        "value_accuracy": (value_correct / name_matched) if name_matched else None,
        "misreads": misreads[:10],
        "missed": missed[:10],
        "summary_findings": len(findings),
        "summary_coverage": (len(findings) / len(truth)) if truth else None,
        "flags": len(ctx.interpretations),
        "flag_counts": {s: sum(1 for f in ctx.interpretations if f.status == s)
                        for s in ("low", "normal", "high", "critical", "unknown")},
        "narrative_chars": len((ctx.summary.content.get("narrative_en") or "")) if ctx.summary else 0,
        "narrative_review": (ctx.summary.content.get("narrative_review") or []) if ctx.summary else [],
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "total_s": round(sum(timings.values()), 2),
        "audit": audit,
        "error": error,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdfs", nargs="+", required=True)
    ap.add_argument("--env", default="dev_4060")
    ap.add_argument("--stages", nargs="+",
                    default=["intake", "ocr", "summary", "interpret", "intake_qa"])
    ap.add_argument("--label", default="")
    ap.add_argument("--force-ocr", action="store_true",
                    help="render pages to PNG and submit as images, so the OCR "
                         "engine runs instead of the PDF text-layer fast path")
    ap.add_argument("--render-dpi", type=int, default=200)
    args = ap.parse_args()

    import models  # noqa: F401  (register adapters)
    from core.pipeline import Pipeline

    pipeline = Pipeline(env_name=args.env)
    rows = []
    for spec in args.pdfs:
        pdf = Path(spec)
        if not pdf.exists():
            raise SystemExit(f"missing pdf: {pdf}")
        print(f"--- {pdf.name} ---", flush=True)
        row = run_one(pdf, pipeline, args.stages, args.force_ocr, args.render_dpi)
        row["force_ocr"] = args.force_ocr
        rows.append(row)
        rc = "n/a" if row["recall"] is None else f"{row['recall']:.0%}"
        va = "n/a" if row["value_accuracy"] is None else f"{row['value_accuracy']:.0%}"
        print(f"    truth={row['truth_values']} extracted={row['extracted_values']} "
              f"recall={rc} value_acc={va} findings={row['summary_findings']} "
              f"flags={row['flags']} {row['total_s']}s"
              + (f"  ERROR {row['error']}" if row["error"] else ""), flush=True)
        for a, want, gotv in row["misreads"]:
            print(f"      MISREAD {a}: want {want}, got {gotv}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    llm = pipeline.config.models.get("llm", {}).get("primary", {})
    meta = {
        "repo": ROOT.name,
        "label": args.label,
        "env": args.env,
        "llm": llm.get("impl"),
        "llm_model": llm.get("model"),
        "image_tag": pipeline.config.models.get("image_tag", {}).get("primary", {}).get("impl"),
        "ocr": pipeline.config.models.get("ocr", {}).get("primary", {}).get("impl"),
    }
    (OUT_DIR / "latest_real.json").write_text(
        json.dumps({"meta": meta, "rows": rows}, indent=2, default=str), encoding="utf-8")

    total_truth = sum(r["truth_values"] for r in rows)
    total_hit = sum(round((r["recall"] or 0) * r["truth_values"]) for r in rows)
    lines = [
        "# Real-report bench (measured)", "",
        f"- repo: `{meta['repo']}`  ·  label: {meta['label'] or '—'}",
        f"- llm: `{meta['llm']}` ({meta['llm_model']})  ·  tagger: `{meta['image_tag']}`"
        f"  ·  ocr: `{meta['ocr']}`", "",
        f"- input mode: **{'RENDERED IMAGES -> OCR engine' if args.force_ocr else 'PDF text layer (OCR bypassed)'}**"
        + (f" @ {args.render_dpi} dpi" if args.force_ocr else ""), "",
        "| report | pages | truth values | extracted | recall | value acc | summary findings | flags | narrative | total s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rc = "n/a" if r["recall"] is None else f"{r['recall']:.0%}"
        va = "n/a" if r["value_accuracy"] is None else f"{r['value_accuracy']:.0%}"
        lines.append(
            f"| {r['pdf']} | {r['pages']} | {r['truth_values']} | {r['extracted_values']} | "
            f"{rc} | {va} | {r['summary_findings']} | {r['flags']} | {r['narrative_chars']} ch | {r['total_s']} |")
    tot_nm = sum(r["name_matched"] for r in rows)
    tot_vc = sum(r["value_correct"] for r in rows)
    lines += ["", f"**Overall extraction recall: {total_hit}/{total_truth} "
                  f"= {(total_hit/total_truth if total_truth else 0):.1%}**",
              f"**Overall value accuracy: {tot_vc}/{tot_nm} "
              f"= {(tot_vc/tot_nm if tot_nm else 0):.1%}**", ""]
    for r in rows:
        if r["missed"]:
            lines.append(f"- `{r['pdf']}` missed: " + ", ".join(f"{a}={v}" for a, v in r["missed"]))
        if r["misreads"]:
            lines.append(f"- `{r['pdf']}` MISREAD: "
                         + ", ".join(f"{a}: want {w}, got {g}" for a, w, g in r["misreads"]))
        if r["narrative_review"]:
            lines.append(f"- `{r['pdf']}` narrative review: " + "; ".join(r["narrative_review"]))
        if r["error"]:
            lines.append(f"- `{r['pdf']}` ERROR: {r['error']}")
    (OUT_DIR / "REPORT_REAL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_DIR/'REPORT_REAL.md'}")


if __name__ == "__main__":
    main()
