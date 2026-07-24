"""Pipeline orchestration used by both the Streamlit app and the test harness.

Thin on purpose: builds the ordered stages, runs one or all of them against a
SessionContext, and (optionally) persists the result. Each stage is invoked via
its ``__call__`` so load/unload wrap every run (VRAM freed even on error).
"""

from __future__ import annotations

import uuid

import models  # noqa: F401  (imports register model adapters with ModelManager)
from core.context import SessionContext
from core.env import AppConfig
from core.model_manager import ModelManager
from core.stage import Stage
from stages import build_pipeline


def new_session(lang: str = "hi") -> SessionContext:
    ctx = SessionContext(session_id=uuid.uuid4().hex[:12], lang=lang)
    ctx.log("session.created", detail=f"lang={lang}")
    return ctx


class Pipeline:
    def __init__(self, env_name: str | None = None) -> None:
        self.config = AppConfig.load(env_name)
        self.models = ModelManager(self.config)
        self.stages: list[Stage] = build_pipeline(self.config, self.models)

    def stage_by_name(self, name: str) -> Stage:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(f"No stage named '{name}'. Have: {[s.name for s in self.stages]}")

    def run_stage(self, name: str, ctx: SessionContext) -> SessionContext:
        return self.stage_by_name(name)(ctx)

    def run_all(self, ctx: SessionContext) -> SessionContext:
        for stage in self.stages:
            ctx = stage(ctx)
        return ctx
