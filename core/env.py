"""EnvProfile: the hardware/deployment abstraction.

One codebase runs on three environments (ARCHITECTURE.md section 1):
    dev_4060  -> RTX 4060 8 GB laptop (tightest VRAM, build here now)
    cloud     -> provider GPU or CPU (loosest)
    orin      -> Jetson Orin NX 16GB ARM (production, later)

The active profile is selected at startup via the ``SS_ENV`` env var and the
matching ``config/env/<name>.yaml``. No stage may read hardware facts directly;
they go through the EnvProfile so that swapping environments is a config change.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

VALID_ENVS = ("dev_4060", "cloud", "orin")
DEFAULT_ENV = "dev_4060"
ENV_VAR = "SS_ENV"

CONFIG_ENV_DIR = Path(__file__).resolve().parent.parent / "config" / "env"


class EnvProfile(BaseModel):
    """Resolved facts about the environment the app is running in.

    Everything hardware- or deployment-sensitive lives here so the rest of the
    code can stay environment-agnostic.
    """

    name: str
    device: str = "cpu"                       # "cuda" | "cpu" | "cuda:0" ...
    vram_ceiling_mb: int = 0                   # 0 = no GPU / not enforced
    max_resident_gpu_models: int = 1           # 8 GB laptop policy = 1
    default_precision: str = "fp16"            # fp16 | int8 | int4 | fp32
    internet_allowed: bool = False             # offline-first is the default
    arch: str = "x86"                          # x86 | arm
    encrypt_at_rest: bool = False              # privacy seam; no-op locally is OK
    data_dir: str = "./_session_data"          # where session artifacts land

    @classmethod
    def load(cls, name: str | None = None) -> "EnvProfile":
        """Load a profile from config/env/<name>.yaml.

        Resolution order: explicit arg -> SS_ENV -> DEFAULT_ENV.
        """
        resolved = name or os.environ.get(ENV_VAR) or DEFAULT_ENV
        if resolved not in VALID_ENVS:
            raise ValueError(
                f"Unknown SS_ENV '{resolved}'. Expected one of {VALID_ENVS}."
            )

        path = CONFIG_ENV_DIR / f"{resolved}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"Env profile config missing: {path}. "
                f"Create it (see config/env/dev_4060.yaml)."
            )

        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        raw.setdefault("name", resolved)
        return cls(**raw)

    @property
    def is_gpu(self) -> bool:
        return self.device.startswith("cuda")


class AppConfig(BaseModel):
    """Top-level config: the active env profile plus the model + stage registries.

    ``models`` mirrors config/models.yaml verbatim; ModelManager reads it to
    resolve a logical model name to a concrete adapter + device + precision.
    ``stages`` mirrors config/stages.yaml (per-stage thresholds/sizes/paths).
    """

    env: EnvProfile
    models: dict = Field(default_factory=dict)
    stages: dict = Field(default_factory=dict)

    @classmethod
    def load(cls, env_name: str | None = None) -> "AppConfig":
        env = EnvProfile.load(env_name)
        config_dir = Path(__file__).resolve().parent.parent / "config"
        return cls(
            env=env,
            models=cls._read_yaml(config_dir / "models.yaml"),
            stages=cls._read_yaml(config_dir / "stages.yaml"),
        )

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def stage_cfg(self, name: str) -> dict:
        """Return the config block for a stage (empty dict if absent)."""
        return self.stages.get(name, {})
