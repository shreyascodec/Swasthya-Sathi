"""Phase 0 acceptance tests (PLAN.md Phase 0).

Acceptance: empty pipeline runs end-to-end passing a context through 9 no-op
stages; VRAM free/used accounting works and unload frees it; a stage can run
standalone in the harness.
"""

from __future__ import annotations

import pytest

import models  # noqa: F401  (registers the dummy adapter)
from core.env import AppConfig, EnvProfile
from core.model_manager import ModelManager, VRAMBudgetError
from core.pipeline import Pipeline, new_session
from tests.harness import run_stage_on_fixture


# --- env profiles ------------------------------------------------------------
@pytest.mark.parametrize("name", ["dev_4060", "cloud", "orin"])
def test_all_env_profiles_load(name: str) -> None:
    env = EnvProfile.load(name)
    assert env.name == name
    assert env.max_resident_gpu_models >= 1


def test_dev_profile_is_8gb_one_model() -> None:
    env = EnvProfile.load("dev_4060")
    assert env.vram_ceiling_mb == 8192
    assert env.max_resident_gpu_models == 1
    assert env.internet_allowed is False  # offline-first


# --- pipeline flows through 9 no-op stages -----------------------------------
def test_pipeline_runs_end_to_end() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    assert [s.order for s in pipeline.stages] == list(range(1, 10))

    ctx = new_session(lang="hi")
    ctx = pipeline.run_all(ctx)

    actions = [e.action for e in ctx.audit]
    # Each stage emits an audit action (still-no-op stages -> .noop; implemented
    # stages -> their own action, e.g. stage.intake.done).
    for stage in pipeline.stages:
        assert any(a.startswith(f"stage.{stage.name}.") for a in actions)


def test_stage_runs_standalone_in_harness() -> None:
    # 'hashing' runs standalone against the fixture — a good canary for the harness.
    ctx = run_stage_on_fixture("hashing", env_name="dev_4060")
    assert any(e.action == "stage.hashing.done" for e in ctx.audit)


# --- ModelManager VRAM load/unload -------------------------------------------
def _cfg() -> AppConfig:
    return AppConfig.load("dev_4060")


def test_vram_freed_on_release() -> None:
    cfg = _cfg()
    mm = ModelManager(cfg)
    free_before = mm.vram_free_mb()

    mm.get("dummy_heavy")  # 2048 MB dummy GPU model
    assert "dummy_heavy" in mm.loaded
    free_loaded = mm.vram_free_mb()
    assert free_loaded <= free_before

    mm.release("dummy_heavy")
    assert "dummy_heavy" not in mm.loaded
    # Freed estimate returns to (at least) where it started.
    assert mm.vram_free_mb() >= free_loaded


def test_one_heavy_model_policy_on_4060() -> None:
    """max_resident_gpu_models=1: loading a second GPU model evicts the first."""
    cfg = _cfg()
    mm = ModelManager(cfg)
    mm.get("dummy_heavy")
    # Second GPU model of same size; policy must evict the first.
    mm.config.models["dummy_heavy2"] = {"primary": {"impl": "dummy", "device": "cuda", "size_mb": 2048}}
    mm.get("dummy_heavy2")
    resident_gpu = [n for n in mm.loaded]
    assert resident_gpu == ["dummy_heavy2"]
    mm.release_all()


def test_budget_error_when_over_ceiling() -> None:
    cfg = _cfg()
    mm = ModelManager(cfg)
    mm.config.models["too_big"] = {"primary": {"impl": "dummy", "device": "cuda", "size_mb": 999999}}
    with pytest.raises(VRAMBudgetError):
        mm.get("too_big")
