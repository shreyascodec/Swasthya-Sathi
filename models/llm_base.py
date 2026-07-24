"""Shared LLM adapter contract for Summary Generation (Phase 4).

An LLM adapter is a ModelManager model: it loads (INT4, one resident at a time
on the 4060), generates text from a (system, user) prompt, and unloads to free
VRAM. Concrete adapters wrap Ollama (Qwen) and HF Transformers (Sarvam/MedGemma).

``LLMUnavailable`` subclasses ImportError so the stage's graceful-fallback path
(to the stub) catches both missing-deps and server-unreachable cases.
"""

from __future__ import annotations

from core.env import EnvProfile


class LLMUnavailable(ImportError):
    """Raised when an LLM runtime is missing or unreachable."""


class LLMAdapterBase:
    default_vram_mb: int = 2600     # ~Qwen2.5-3B INT4

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self.device: str = spec.get("device", env.device)
        self.is_gpu: bool = self.device.startswith("cuda")
        self._vram_mb: int = int(spec.get("vram_mb", self.default_vram_mb))
        self.model_id: str = spec.get("model", "")
        self.is_instruct: bool = bool(spec.get("instruct", True))
        self._handle = None

    def load(self) -> None:
        if self._handle is None:
            self._handle = self._build()

    def unload(self) -> None:
        self._handle = None

    def vram_mb(self) -> int:
        return self._vram_mb if self.is_gpu else 0

    def generate(self, system: str, user: str, max_tokens: int = 1024,
                 temperature: float = 0.0) -> str:
        self.load()
        return self._generate(system, user, max_tokens, temperature)

    # -- to implement -----------------------------------------------------
    def _build(self):  # pragma: no cover - runtime specific
        return None

    def _generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:  # pragma: no cover
        raise NotImplementedError
