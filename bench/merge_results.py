"""Merge single-model rerun results into a main bake-off results file.

Usage:
    python -m bench.merge_results --main bench/results --patch bench/results_airavata

Replaces (by model name) each model block from the patch run into the main
results, recomputes is_sample, and regenerates CSV/REPORT/charts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.runner import _write_charts, _write_csv, _write_json, _write_report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default="bench/results")
    ap.add_argument("--patch", default="bench/results_airavata")
    args = ap.parse_args()

    main_dir, patch_dir = Path(args.main), Path(args.patch)
    results = json.loads((main_dir / "latest.json").read_text(encoding="utf-8"))
    patch = json.loads((patch_dir / "latest.json").read_text(encoding="utf-8"))

    by_name = {m["name"]: m for m in patch["models"]}
    replaced = []
    for i, m in enumerate(results["models"]):
        if m["name"] in by_name:
            results["models"][i] = by_name[m["name"]]
            replaced.append(m["name"])

    results["is_sample"] = any(m["is_stub"] for m in results["models"])
    results["sample_note"] = (
        "SAMPLE — at least one model ran on the STUB." if results["is_sample"]
        else "Real measurements."
    )
    # Keep the later timestamp so the report reflects the newest data.
    results["generated_at"] = max(results["generated_at"], patch["generated_at"])

    _write_json(results, main_dir / "latest.json")
    _write_csv(results, main_dir / "summary.csv")
    _write_report(results, main_dir / "REPORT.md")
    _write_charts(results, main_dir)
    print(f"Merged {replaced} into {main_dir}. is_sample={results['is_sample']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
