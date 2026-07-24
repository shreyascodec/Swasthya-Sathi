"""The Stage ABC — the backbone contract every pipeline stage implements.

A stage acquires its model (load), does its work (run), and frees VRAM
(unload). Stages communicate only through SessionContext. Because the shape is
uniform, any stage can be benched in isolation and any model can be swapped
behind it via config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.context import SessionContext
from core.env import AppConfig
from core.model_manager import ModelManager


class Stage(ABC):
    """Base class for all pipeline stages.

    Subclasses set ``name`` and ``order`` and implement ``run``. ``load`` and
    ``unload`` default to no-ops for stages that hold no heavy model (e.g. the
    classical-CV intake gate or the rule-based interpreter).
    """

    name: str = "unnamed"
    order: int = 0                    # position in the pipeline (1..9)
    description: str = ""

    def __init__(self, config: AppConfig, models: ModelManager) -> None:
        self.config = config
        self.models = models

    def load(self) -> None:
        """Acquire model/VRAM. Idempotent. No-op by default."""
        return None

    def unload(self) -> None:
        """Release model/VRAM. Critical on the 8 GB laptop. No-op by default."""
        return None

    @abstractmethod
    def run(self, ctx: SessionContext) -> SessionContext:
        """Read from ctx, do the work, write results back to ctx, return it."""
        raise NotImplementedError

    def __call__(self, ctx: SessionContext) -> SessionContext:
        """Convenience: load -> run -> unload with a guaranteed unload."""
        self.load()
        try:
            return self.run(ctx)
        finally:
            self.unload()
