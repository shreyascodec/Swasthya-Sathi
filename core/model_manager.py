"""ModelManager — single owner of model lifecycle and device placement.

Stages ask for a model by *logical name* (e.g. "llm", "ocr"). ModelManager
resolves the concrete adapter + device + precision from config for the active
EnvProfile, loads it (unloading others first if the env's resident-GPU-model
policy requires it), and hands back a handle.

On the 8 GB laptop the policy is ``max_resident_gpu_models = 1`` so loading a
second heavy GPU model automatically frees the first. On cloud/orin the same
code relaxes the policy from config — no code change.
"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from core.env import AppConfig, EnvProfile

log = logging.getLogger("swasthya.model_manager")


def _torch():
    """Import torch lazily; return the module or None if unavailable.

    torch is optional in Phase 0 so the skeleton runs on a bare CPU box with no
    CUDA wheels. When present, it is used for real VRAM accounting.
    """
    try:
        import torch  # type: ignore

        return torch
    except Exception:  # pragma: no cover - depends on host
        return None


def cuda_vram_free_mb() -> int | None:
    """Free CUDA VRAM in MB, or None if CUDA/torch is unavailable."""
    torch = _torch()
    if torch is None or not torch.cuda.is_available():
        return None
    free_bytes, _total = torch.cuda.mem_get_info()
    return int(free_bytes // (1024 * 1024))


class ModelAdapter(Protocol):
    """Minimal contract every model adapter honors (see models/)."""

    logical_name: str
    is_gpu: bool

    def load(self) -> None: ...
    def unload(self) -> None: ...
    def vram_mb(self) -> int: ...


# Registry of impl-name -> adapter factory. Adapters register themselves so
# ModelManager stays decoupled from concrete impls. Phase 0 ships only "dummy".
_ADAPTER_FACTORIES: dict[str, Callable[..., ModelAdapter]] = {}


def register_adapter(impl: str, factory: Callable[..., ModelAdapter]) -> None:
    _ADAPTER_FACTORIES[impl] = factory


class VRAMBudgetError(RuntimeError):
    """Raised when a load would exceed the env VRAM ceiling. Fail loud, not OOM."""


class ModelManager:
    def __init__(self, config: AppConfig, env: EnvProfile | None = None) -> None:
        self.config = config
        self.env = env or config.env
        self._loaded: dict[str, ModelAdapter] = {}

    # -- resolution -------------------------------------------------------
    def _resolve_spec(self, logical_name: str) -> dict:
        """Pull the primary spec for a logical model from config/models.yaml."""
        section = self.config.models.get(logical_name)
        if section is None:
            raise KeyError(
                f"No config for logical model '{logical_name}' in models.yaml."
            )
        spec = dict(section.get("primary", section))
        spec.setdefault("device", self.env.device)
        spec.setdefault("precision", self.env.default_precision)
        return spec

    # -- lifecycle --------------------------------------------------------
    def get(
        self,
        logical_name: str,
        factory: Callable[..., ModelAdapter] | None = None,
    ) -> ModelAdapter:
        """Return a loaded adapter for ``logical_name``, loading it if needed.

        Enforces the env's ``max_resident_gpu_models`` policy by releasing the
        oldest resident GPU model(s) before loading a new GPU model.
        """
        if logical_name in self._loaded:
            return self._loaded[logical_name]

        spec = self._resolve_spec(logical_name)
        impl = spec.get("impl", "dummy")
        make = factory or _ADAPTER_FACTORIES.get(impl)
        if make is None:
            raise KeyError(
                f"No adapter registered for impl '{impl}'. "
                f"Register one via register_adapter() or pass a factory."
            )

        adapter = make(logical_name=logical_name, spec=spec, env=self.env)
        # `pinned` marks a model that is small enough to stay resident and
        # expensive enough to load that evicting it costs more than the slot is
        # worth (Kokoro TTS: ~330 MB, ~10 s to re-materialise). Set here rather
        # than read from the adapter so it works for any adapter shape.
        adapter.pinned = bool(spec.get("pinned", False))

        if getattr(adapter, "is_gpu", False):
            self._enforce_gpu_policy()
            self._check_budget(adapter)

        log.info("Loading model '%s' (impl=%s, device=%s)", logical_name, impl, spec.get("device"))
        adapter.load()
        self._loaded[logical_name] = adapter
        self._log_vram("after load %s" % logical_name)
        return adapter

    def release(self, logical_name: str) -> None:
        adapter = self._loaded.pop(logical_name, None)
        if adapter is None:
            return
        log.info("Unloading model '%s'", logical_name)
        adapter.unload()
        # Quantized/accelerate models leave reference cycles; without an
        # explicit gc pass their CUDA tensors are still alive when
        # empty_cache() runs and the VRAM is never returned to the driver.
        import gc
        gc.collect()
        torch = _torch()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._log_vram("after release %s" % logical_name)

    def release_all(self) -> None:
        for name in list(self._loaded):
            self.release(name)

    # -- policy -----------------------------------------------------------
    def _resident_gpu(self) -> list[str]:
        return [n for n, a in self._loaded.items() if getattr(a, "is_gpu", False)]

    def _enforce_gpu_policy(self) -> None:
        limit = self.env.max_resident_gpu_models
        # Pinned models are never chosen as victims: the policy counts *heavy*
        # models, and evicting a 330 MB always-needed one to make room is a net
        # loss. They still count against the VRAM ceiling in _check_budget, so
        # the card cannot be oversubscribed by pinning.
        resident = [n for n in self._resident_gpu()
                    if not getattr(self._loaded[n], "pinned", False)]
        # We're about to add one more, so free until there's room for it.
        while len(resident) >= limit and resident:
            victim = resident.pop(0)
            log.info(
                "GPU policy (max=%d) forces release of '%s' before loading next",
                limit, victim,
            )
            self.release(victim)

    def _check_budget(self, adapter: ModelAdapter) -> None:
        ceiling = self.env.vram_ceiling_mb
        if ceiling <= 0:
            return
        need = adapter.vram_mb()
        free = self.vram_free_mb()
        if need > free:
            raise VRAMBudgetError(
                f"Loading '{adapter.logical_name}' needs ~{need} MB but only "
                f"{free} MB free (ceiling {ceiling} MB). Release a resident "
                f"model first. Currently resident GPU models: {self._resident_gpu()}"
            )

    # -- introspection ----------------------------------------------------
    def vram_free_mb(self) -> int:
        """Best-effort free VRAM. Real if torch+CUDA, else budgeted estimate."""
        real = cuda_vram_free_mb()
        if real is not None:
            return real
        used = sum(a.vram_mb() for a in self._loaded.values() if getattr(a, "is_gpu", False))
        return max(self.env.vram_ceiling_mb - used, 0)

    @property
    def loaded(self) -> list[str]:
        return list(self._loaded)

    def _log_vram(self, when: str) -> None:
        log.info("VRAM free ~%d MB (%s); resident=%s", self.vram_free_mb(), when, self.loaded)
