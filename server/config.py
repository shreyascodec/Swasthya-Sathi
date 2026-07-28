"""Server runtime configuration, read from the environment.

Deploy knob surface for the kiosk: everything the *server layer* needs to run in
a real deployment (bind address, allowed origins, log level, session lifetime,
warmup) comes from ``SS_``-prefixed env vars with kiosk-safe defaults, so the
same image runs on the dev laptop and the Orin without code edits. The *engine*
is still configured separately by ``SS_ENV`` + ``config/env/<name>.yaml`` — this
file does not touch that.

Kept dependency-free (plain ``os.environ`` + pydantic, both already present); no
``pydantic-settings`` dependency is added.
"""

from __future__ import annotations

import os

from pydantic import BaseModel

_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def _bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ServerConfig(BaseModel):
    """Resolved server-layer settings. Immutable after load."""

    host: str = "127.0.0.1"
    port: int = 8000
    # In a single-origin kiosk build the SPA is served from this same process, so
    # no cross-origin requests happen and this can be empty. It defaults to the
    # Vite dev server so `npm run dev` works out of the box.
    allowed_origins: list[str] = _DEV_ORIGINS
    log_level: str = "INFO"
    session_ttl_seconds: int = 1800      # idle sessions reaped (+ their data dir) after this
    max_sessions: int = 64
    warmup: bool = True                  # load models at startup, not on the first patient
    persist_reports: bool = True         # write report_v<n>.json into the session data dir

    @classmethod
    def from_env(cls) -> "ServerConfig":
        kw: dict = {}
        env = os.environ
        if "SS_HOST" in env:
            kw["host"] = env["SS_HOST"].strip()
        if "SS_PORT" in env:
            kw["port"] = int(env["SS_PORT"])
        if "SS_ALLOWED_ORIGINS" in env:
            # comma-separated; empty string ⇒ same-origin only (no CORS)
            kw["allowed_origins"] = [o.strip() for o in env["SS_ALLOWED_ORIGINS"].split(",") if o.strip()]
        if "SS_LOG_LEVEL" in env:
            kw["log_level"] = env["SS_LOG_LEVEL"].strip().upper()
        if "SS_SESSION_TTL_SECONDS" in env:
            kw["session_ttl_seconds"] = int(env["SS_SESSION_TTL_SECONDS"])
        if "SS_MAX_SESSIONS" in env:
            kw["max_sessions"] = int(env["SS_MAX_SESSIONS"])
        if "SS_WARMUP" in env:
            kw["warmup"] = _bool(env["SS_WARMUP"])
        if "SS_PERSIST_REPORTS" in env:
            kw["persist_reports"] = _bool(env["SS_PERSIST_REPORTS"])
        return cls(**kw)
