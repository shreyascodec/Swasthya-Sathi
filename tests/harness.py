"""Per-stage test harness.

Run any single stage against a saved SessionContext fixture without clicking
through the whole UI — this is how models get benched per stage. Also exposes a
helper to build a fresh in-memory context.

Usage (from repo root):
    python -m tests.harness ocr                 # run stage 'ocr' on the fixture
    python -m tests.harness --list              # list stage names
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.context import SessionContext
from core.pipeline import Pipeline, new_session

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_FIXTURE = FIXTURE_DIR / "sample_context.json"


def load_fixture(path: str | Path = DEFAULT_FIXTURE) -> SessionContext:
    path = Path(path)
    if path.exists():
        return SessionContext.model_validate_json(path.read_text(encoding="utf-8"))
    return new_session(lang="hi")


def run_stage_on_fixture(
    stage_name: str,
    fixture: str | Path = DEFAULT_FIXTURE,
    env_name: str | None = None,
) -> SessionContext:
    pipeline = Pipeline(env_name=env_name)
    ctx = load_fixture(fixture)
    return pipeline.run_stage(stage_name, ctx)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run one pipeline stage on a fixture.")
    parser.add_argument("stage", nargs="?", help="stage name, e.g. 'ocr'")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--env", default=None, help="SS_ENV override")
    parser.add_argument("--list", action="store_true", help="list stage names")
    args = parser.parse_args(argv)

    pipeline = Pipeline(env_name=args.env)
    if args.list or not args.stage:
        print("Stages:", [f"{s.order}:{s.name}" for s in pipeline.stages])
        return 0

    ctx = run_stage_on_fixture(args.stage, args.fixture, args.env)
    print(f"Ran '{args.stage}'. Audit trail:")
    for e in ctx.audit:
        print(f"  {e.ts.isoformat(timespec='seconds')} {e.action} ({e.detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
