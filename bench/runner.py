"""Summary-generation bake-off runner — produces the stakeholder proof.

For each candidate LLM it runs the labeled eval set, scores every metric, and
writes:  results JSON, CSV, a markdown REPORT, and PNG charts. If a real runtime
(Ollama/Transformers) is unavailable it falls back to the stub and marks the run
as SAMPLE so nobody mistakes stub output for real measurements.

Run on the 4060 (Ollama running + models pulled/installed):
    python -m bench.make_eval_set        # once, to build the eval set
    python -m bench.runner               # all candidates
    python -m bench.runner --models qwen2.5-3b-instruct,sarvam-1-2b
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import models  # noqa: F401  (register adapters)
from bench.dataset import EvalItem, load_eval_set
from bench.metrics import (
    extraction_prf,
    faithfulness,
    hindi_quality,
    percentile,
)
from core.env import AppConfig
from core.model_manager import ModelManager
from stages.faithfulness import check_faithfulness
from stages.summary_build import build_prompt, parse_summary
from stages.summary_schema import SummarySchema

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _stub_factory():
    from models.llm_stub import StubLLMAdapter

    return lambda logical_name, spec, env: StubLLMAdapter(
        logical_name, {**spec, "device": "cpu"}, env
    )


def _summarize(raw: str, lang: str) -> SummarySchema:
    try:
        return SummarySchema.model_validate(parse_summary(raw))
    except Exception:
        return SummarySchema(patient_language=lang, unknowns=["parse_error"])


def run_model(spec: dict, items: list[EvalItem], env_name: str | None,
              force_stub: bool = False) -> dict:
    """Run one candidate over the eval set; returns its result block."""
    config = AppConfig.load(env_name)
    config.models["llm"]["primary"] = spec
    mm = ModelManager(config)

    is_stub = False
    if force_stub:
        adapter = mm.get("llm", factory=_stub_factory())
        is_stub = True
    else:
        try:
            adapter = mm.get("llm")   # real runtime (Ollama/Transformers)
        except Exception as exc:      # missing deps, server down, no weights, etc.
            print(f"  [fallback] {spec.get('name')} load failed -> stub: "
                  f"{type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
            mm.release("llm")
            adapter = mm.get("llm", factory=_stub_factory())
            is_stub = True

    per_item: list[dict] = []
    for item in items:
        system, user = build_prompt(item.ocr_fields, item.lang)
        t0 = time.perf_counter()
        try:
            raw = adapter.generate(system, user)
        except Exception as exc:
            # A real model failed mid-run: fall back to the stub and mark SAMPLE.
            if not is_stub:
                print(f"  [fallback] {spec.get('name')} generate failed on "
                      f"{item.id} -> stub: {type(exc).__name__}: {str(exc)[:200]}",
                      file=sys.stderr)
                mm.release("llm")
                adapter = mm.get("llm", factory=_stub_factory())
                is_stub = True
            raw = adapter.generate(system, user)
        latency = time.perf_counter() - t0

        summary = _summarize(raw, item.lang)
        report = check_faithfulness(summary, item.ocr_fields)
        prf = extraction_prf(summary, item.gold)
        hq = hindi_quality(summary, item.gold) if item.lang == "hi" else None

        per_item.append({
            "id": item.id, "lang": item.lang,
            "latency_s": round(latency, 4),
            "faithfulness": round(report.faithfulness, 4),
            "hallucination_rate": round(report.hallucination_rate, 4),
            "issues": len(report.issues),
            "precision": round(prf["precision"], 4),
            "recall": round(prf["recall"], 4),
            "f1": round(prf["f1"], 4),
            "hindi_quality": hq,
        })

    mm.release("llm")  # free VRAM before the next candidate

    def mean(key, cond=lambda pi: True):
        vals = [pi[key] for pi in per_item if cond(pi) and pi[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    latencies = [pi["latency_s"] for pi in per_item]
    faith_vals = [pi["faithfulness"] for pi in per_item]
    metrics = {
        "faithfulness": mean("faithfulness"),
        "hallucination_rate": mean("hallucination_rate"),
        "faithfulness_pass_rate": round(
            sum(1 for v in faith_vals if v >= 1.0) / len(faith_vals), 4) if faith_vals else 0.0,
        "extraction_precision": mean("precision"),
        "extraction_recall": mean("recall"),
        "extraction_f1": mean("f1"),
        "hindi_quality": mean("hindi_quality", lambda pi: pi["lang"] == "hi"),
        "latency_s_mean": round(sum(latencies) / len(latencies), 4) if latencies else 0.0,
        "latency_s_p90": round(percentile(latencies, 0.9), 4),
    }

    return {
        "name": spec.get("name", spec.get("impl", "unknown")),
        "impl": spec.get("impl"),
        "runtime": "stub(fallback)" if is_stub else spec.get("runtime", spec.get("impl")),
        "model_id": spec.get("model", ""),
        "is_stub": is_stub,
        "vram_budget_mb": spec.get("vram_mb", 0),
        "vram_measured_mb": adapter.vram_mb(),
        "metrics": metrics,
        "per_item": per_item,
    }


def run(models_filter: list[str] | None, env_name: str | None,
        eval_path: str | None, out_dir: Path, force_stub: bool = False) -> dict:
    config = AppConfig.load(env_name)
    candidates = config.models.get("llm", {}).get("candidates", [])
    if models_filter:
        candidates = [c for c in candidates if c.get("name") in models_filter]
    if not candidates:
        raise SystemExit("No candidates matched. Check config/models.yaml llm.candidates.")

    items = load_eval_set(eval_path) if eval_path else load_eval_set()
    langs: dict[str, int] = {}
    for it in items:
        langs[it.lang] = langs.get(it.lang, 0) + 1

    model_results = [run_model(spec, items, env_name, force_stub) for spec in candidates]
    is_sample = any(m["is_stub"] for m in model_results)

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "env": config.env.name,
        "is_sample": is_sample,
        "sample_note": (
            "SAMPLE — at least one model ran on the STUB (no real runtime found). "
            "Run on the 4060 with Ollama/Transformers for real measurements."
            if is_sample else "Real measurements."
        ),
        "dataset": {"n": len(items), "langs": langs},
        "models": model_results,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results, out_dir / "latest.json")
    _write_csv(results, out_dir / "summary.csv")
    _write_report(results, out_dir / "REPORT.md")
    _write_charts(results, out_dir)
    return results


# --- outputs -----------------------------------------------------------------
def _write_json(results: dict, path: Path) -> None:
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


_METRIC_COLS = [
    "faithfulness", "hallucination_rate", "faithfulness_pass_rate",
    "extraction_precision", "extraction_recall", "extraction_f1",
    "hindi_quality", "latency_s_mean", "latency_s_p90",
]


def _write_csv(results: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "runtime", "vram_budget_mb", *_METRIC_COLS])
        for m in results["models"]:
            w.writerow([m["name"], m["runtime"], m["vram_budget_mb"],
                        *[m["metrics"][c] for c in _METRIC_COLS]])


def _write_report(results: dict, path: Path) -> None:
    lines = [
        "# Summary-Generation Model Bake-off",
        "",
        f"- Generated: {results['generated_at']}  ·  Env: `{results['env']}`",
        f"- Dataset: {results['dataset']['n']} reports {results['dataset']['langs']}",
        "",
    ]
    if results["is_sample"]:
        lines += [f"> **{results['sample_note']}**", ""]

    lines += [
        "## Results",
        "",
        "| Model | Runtime | VRAM (MB) | Faithful | Halluc. | Pass% | Extract F1 | Hindi | Lat mean (s) | Lat p90 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in results["models"]:
        x = m["metrics"]
        lines.append(
            f"| {m['name']} | {m['runtime']} | {m['vram_budget_mb']} | "
            f"{x['faithfulness']:.2f} | {x['hallucination_rate']:.2f} | "
            f"{x['faithfulness_pass_rate']*100:.0f}% | {x['extraction_f1']:.2f} | "
            f"{x['hindi_quality']:.2f} | {x['latency_s_mean']:.2f} | {x['latency_s_p90']:.2f} |"
        )

    lines += [
        "",
        "## How to read this",
        "- **Faithful / Halluc. / Pass%**: fraction of summary values that trace to an "
        "OCR field. This is the safety headline — hallucinated medical values are "
        "disqualifying regardless of other scores.",
        "- **Extract F1**: precision/recall of structured lab findings vs gold labels.",
        "- **Hindi**: proxy score (Devanagari density + grounded-value coverage). "
        "Final Hindi quality needs a clinician read.",
        "- **Latency / VRAM**: p90 latency and the INT4 VRAM budget (must fit 8 GB on the 4060).",
        "",
        "## Method",
        "Each model fills a fixed structured schema from OCR fields only (no free chat). "
        "Every candidate sees identical prompts and eval items. Metrics are averaged over "
        "the eval set; Hindi quality over Hindi items only.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_charts(results: dict, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        (out_dir / "CHARTS_SKIPPED.txt").write_text(
            "matplotlib not installed; `pip install matplotlib` to render charts.",
            encoding="utf-8",
        )
        return

    names = [m["name"] for m in results["models"]]
    charts = [
        ("faithfulness", "Faithfulness (higher is better)"),
        ("extraction_f1", "Field extraction F1"),
        ("hindi_quality", "Hindi quality (proxy)"),
        ("latency_s_mean", "Mean latency (s, lower is better)"),
    ]
    for key, title in charts:
        vals = [m["metrics"][key] for m in results["models"]]
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.bar(names, vals, color="#2b7a78")
        ax.set_title(title + ("  [SAMPLE]" if results["is_sample"] else ""))
        ax.set_ylim(0, max(vals) * 1.2 if max(vals) > 0 else 1)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
        fig.tight_layout()
        fig.savefig(out_dir / f"chart_{key}.png", dpi=120)
        plt.close(fig)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the summary-generation model bake-off.")
    parser.add_argument("--models", default=None, help="comma-separated candidate names")
    parser.add_argument("--env", default=None, help="SS_ENV override")
    parser.add_argument("--eval", default=None, help="path to eval_set.json")
    parser.add_argument("--out", default=str(RESULTS_DIR), help="output directory")
    parser.add_argument("--force-stub", action="store_true",
                        help="use the stub for every model (fast, offline demo)")
    args = parser.parse_args(argv)

    filt = [s.strip() for s in args.models.split(",")] if args.models else None
    results = run(filt, args.env, args.eval, Path(args.out), args.force_stub)

    print(f"\nBake-off complete ({'SAMPLE' if results['is_sample'] else 'REAL'}). "
          f"Wrote {args.out}/latest.json, summary.csv, REPORT.md, charts.")
    for m in results["models"]:
        x = m["metrics"]
        print(f"  {m['name']:<24} faith={x['faithfulness']:.2f} "
              f"f1={x['extraction_f1']:.2f} hindi={x['hindi_quality']:.2f} "
              f"lat={x['latency_s_mean']:.2f}s runtime={m['runtime']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
