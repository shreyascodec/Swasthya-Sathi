"""Dummy model adapter — proves the ModelManager VRAM load/unload seam.

It allocates a configurable chunk of memory on load and frees it on unload.
On a CUDA box it allocates real VRAM (so you can verify on the 4060 that VRAM
actually drops back on unload); with no CUDA it allocates host RAM and reports
a simulated VRAM footprint so the policy/budget logic is still exercised.
"""

from __future__ import annotations

import logging

from core.env import EnvProfile
from core.model_manager import register_adapter

log = logging.getLogger("swasthya.models.dummy")


class DummyModel:
    """Allocates ``vram_mb`` of memory to stand in for a heavy model."""

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self._size_mb: int = int(spec.get("size_mb", 512))
        self.device: str = spec.get("device", env.device)
        self.is_gpu: bool = self.device.startswith("cuda")
        self._buffer = None  # holds the allocation while loaded

    def load(self) -> None:
        if self._buffer is not None:
            return  # idempotent
        if self.is_gpu:
            allocated = self._alloc_cuda(self._size_mb)
            if allocated is None:
                # No CUDA on this host: simulate. vram_mb() still reports the
                # footprint so the policy/budget logic is exercised.
                self._buffer = ("simulated-gpu", self._size_mb)
            else:
                self._buffer = allocated
        else:
            # Host allocation: a bytearray of the requested size.
            self._buffer = bytearray(self._size_mb * 1024 * 1024)
        log.info("DummyModel '%s' loaded (~%d MB on %s)", self.logical_name, self._size_mb, self.device)

    def unload(self) -> None:
        self._buffer = None  # drop the reference; frees CPU RAM or CUDA tensor
        log.info("DummyModel '%s' unloaded", self.logical_name)

    def vram_mb(self) -> int:
        return self._size_mb if self.is_gpu else 0

    def _alloc_cuda(self, size_mb: int):
        """Allocate real VRAM if torch+CUDA exist; else return None (simulate)."""
        try:
            import torch  # local import; only reached on a CUDA box

            if not torch.cuda.is_available():
                return None
            elems = (size_mb * 1024 * 1024) // 4  # float32 = 4 bytes
            return torch.empty(int(elems), dtype=torch.float32, device=self.device)
        except Exception:
            return None


def _factory(logical_name: str, spec: dict, env: EnvProfile) -> DummyModel:
    return DummyModel(logical_name=logical_name, spec=spec, env=env)


register_adapter("dummy", _factory)
