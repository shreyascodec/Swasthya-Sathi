"""Per-stage wall-clock bench — real models, real inputs, no estimates.

Runs every pipeline stage in order on a fixed session (two English report pages
+ one clinical photo), timing each stage's full __call__ (load -> run -> unload,
i.e. exactly what a kiosk session pays under the one-heavy-model VRAM policy).
Also times STT answer capture on a clip synthesized by the voice stage.

Usage (from repo root):
    python -m bench.runner_stages --runs 2

Writes bench/results_stages/latest_stages.json and REPORT_STAGES.md.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from core.context import SessionContext, UploadedFile
from core.pipeline import Pipeline, new_session

ROOT = Path(__file__).resolve().parents[1]
REPORT_PAGES = [
    ROOT / "data" / "eval" / "pages" / "multi_00_en_p1.png",
    ROOT / "data" / "eval" / "pages" / "multi_00_en_p2.png",
]
CLINICAL_IMAGE = ROOT / "data" / "clinical" / "skin" / "skin_0.png"
OUT_DIR = ROOT / "bench" / "results_stages"


def fresh_ctx(run_idx: int) -> SessionContext:
    ctx = new_session(lang="hi")
    ctx.session_id = f"stagebench{run_idx}"
    uploads = [
        UploadedFile(id=f"rep{i}", path=str(p), type="image", source_path=str(p))
        for i, p in enumerate(REPORT_PAGES)
    ]
    uploads.append(UploadedFile(id="clin0", path=str(CLINICAL_IMAGE),
                                type="image", source_path=str(CLINICAL_IMAGE)))
    ctx.uploads = uploads
    return ctx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    for p in [*REPORT_PAGES, CLINICAL_IMAGE]:
        if not p.exists():
            raise SystemExit(f"missing bench input: {p}")

    pipeline = Pipeline()
    timings: dict[str, list[float]] = {s.name: [] for s in pipeline.stages}
    timings["stt_answer"] = []
    details: dict[str, str] = {}

    for run in range(args.runs):
        ctx = fresh_ctx(run)
        for stage in pipeline.stages:
            t0 = time.perf_counter()
            ctx = stage(ctx)
            dt = time.perf_counter() - t0
            timings[stage.name].append(round(dt, 3))
            done = [e for e in ctx.audit if e.action == f"stage.{stage.name}.done"]
            if done:
                details[stage.name] = done[-1].detail or ""
            print(f"[run {run}] {stage.name:10s} {dt:8.2f}s  {details.get(stage.name, '')}",
                  flush=True)

        # STT on a real synthesized clip (question wav from the voice stage).
        clip = next((c for c in ctx.audio_out if c.kind == "tts"), None)
        if clip and ctx.questions and Path(clip.path).exists():
            qa = pipeline.stage_by_name("intake_qa")
            t0 = time.perf_counter()
            ans = qa.capture_answer(ctx, ctx.questions[0].id, clip.path)
            dt = time.perf_counter() - t0
            timings["stt_answer"].append(round(dt, 3))
            details["stt_answer"] = f"clip_ms={clip.duration_ms} chars={len(ans.transcript)}"
            print(f"[run {run}] stt_answer {dt:8.2f}s  {details['stt_answer']}", flush=True)

    llm = pipeline.config.models["llm"]["primary"]
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": str(ROOT),
        "runs": args.runs,
        "inputs": {"report_pages": len(REPORT_PAGES), "clinical_images": 1},
        "llm_primary": {"impl": llm.get("impl"), "model": llm.get("model")},
        "image_tag_primary": pipeline.config.models["image_tag"]["primary"].get("impl"),
        "voice_cfg": {k: pipeline.config.stage_cfg("voice").get(k)
                      for k in ("speak_summary", "speak_questions", "translate_summary")},
        "summary_use_images": pipeline.config.stage_cfg("summary").get("use_images"),
    }
    rows = []
    total_mean = 0.0
    for name, vals in timings.items():
        if not vals:
            continue
        mean = statistics.mean(vals)
        if name != "stt_answer":          # stt is interactive, outside stage order
            total_mean += mean
        rows.append({"stage": name, "runs_s": vals, "mean_s": round(mean, 2),
                     "max_s": max(vals), "detail": details.get(name, "")})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "latest_stages.json").write_text(
        json.dumps({"meta": meta, "stages": rows,
                    "pipeline_total_mean_s": round(total_mean, 2)}, indent=2),
        encoding="utf-8")

    md = ["# Per-stage latency (measured)", "",
          f"- generated: {meta['generated_at']}  ·  runs: {args.runs}",
          f"- llm: `{meta['llm_primary']['impl']}` ({meta['llm_primary']['model']})"
          f"  ·  tagger: `{meta['image_tag_primary']}`",
          f"- voice: {meta['voice_cfg']}  ·  summary.use_images: {meta['summary_use_images']}",
          f"- inputs: {len(REPORT_PAGES)} report pages + 1 clinical image", "",
          "| stage | runs (s) | mean (s) | detail |", "|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['stage']} | {', '.join(f'{v:.1f}' for v in r['runs_s'])} "
                  f"| {r['mean_s']:.2f} | {r['detail']} |")
    md += ["", f"**Pipeline total (mean, excl. STT): {total_mean:.1f} s**", ""]
    (OUT_DIR / "REPORT_STAGES.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nwrote {OUT_DIR}\\latest_stages.json and REPORT_STAGES.md "
          f"(total mean {total_mean:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
