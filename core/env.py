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

VALID_ENVS = ("local", "dev_4060", "cloud", "cloud_flagship", "orin")
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
        # Appliance setup writes config/env/local.yaml from hardware detection.
        # If SS_ENV=local but the file is not there yet, fall back to DEFAULT_ENV
        # so a fresh checkout still boots.
        if resolved == "local" and not (CONFIG_ENV_DIR / "local.yaml").exists():
            resolved = DEFAULT_ENV
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
        profile = cls(**raw)
        profile._apply_offline_policy()
        return profile

    def _apply_offline_policy(self) -> None:
        """Make the ML libraries honour ``internet_allowed: false``.

        Without this, every ``KPipeline``/``from_pretrained`` build does hub HEAD
        requests even though the weights are already on disk: cheap on a good
        network, an unbounded socket timeout on the offline kiosk this profile
        describes. ``setdefault`` so an explicit env var still wins.

        Must run before huggingface_hub is imported — its constants are read at
        import time — which is why it lives at profile load, ahead of the lazy
        adapter imports, rather than inside an adapter's ``_build``.
        """
        if self.internet_allowed:
            return
        for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            os.environ.setdefault(var, "1")

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
        models = cls._read_yaml(config_dir / "models.yaml")
        stages = cls._read_yaml(config_dir / "stages.yaml")
        # Per-env overrides: config/models.<env>.yaml and config/stages.<env>.yaml
        # are deep-merged over the base registries. This keeps the edge
        # (dev_4060/orin) config pristine while a bigger box (cloud_flagship)
        # points a stage at a heavier model, or trades a speed shortcut for
        # accuracy (e.g. real OCR over the PDF text-layer bypass) — still a config
        # edit, never a code change. Absent file = no-op.
        m_override = config_dir / f"models.{env.name}.yaml"
        if m_override.exists():
            models = cls._deep_merge(models, cls._read_yaml(m_override))
        s_override = config_dir / f"stages.{env.name}.yaml"
        if s_override.exists():
            stages = cls._deep_merge(stages, cls._read_yaml(s_override))
        return cls(env=env, models=models, stages=stages)

    @staticmethod
    def _deep_merge(base: dict, over: dict) -> dict:
        """Recursively merge ``over`` into a copy of ``base`` (dicts only)."""
        out = dict(base)
        for key, val in (over or {}).items():
            if isinstance(val, dict) and isinstance(out.get(key), dict):
                out[key] = AppConfig._deep_merge(out[key], val)
            else:
                out[key] = val
        return out

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def stage_cfg(self, name: str) -> dict:
        """Return the config block for a stage (empty dict if absent)."""
        return self.stages.get(name, {})
