"""Ollama LLM adapter (primary runtime for Phi-3.5-mini).

Talks to a local Ollama server (offline once the model is pulled). Serves GGUF
INT4 models with a single resident model — a good fit for the 8 GB laptop.

Setup (per phase, on the 4060):
    # install Ollama, then:
    ollama pull phi3.5:3.8b
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from core.model_manager import register_adapter
from models.llm_base import LLMAdapterBase, LLMUnavailable


class OllamaAdapter(LLMAdapterBase):
    default_vram_mb = 2600

    def _endpoint(self) -> str:
        host = os.environ.get("SS_OLLAMA_HOST") or self.spec.get("host", "http://localhost:11434")
        return host.rstrip("/") + "/api/chat"

    def _build(self):
        # Verify the server is reachable so we can fall back cleanly if not.
        host = (os.environ.get("SS_OLLAMA_HOST") or self.spec.get("host", "http://localhost:11434")).rstrip("/")
        try:
            with urllib.request.urlopen(host + "/api/tags", timeout=3) as resp:
                resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise LLMUnavailable(
                f"Ollama server not reachable at {host}. Start it and "
                f"`ollama pull {self.model_id}`, or swap llm to stub_llm."
            ) from exc
        return {"endpoint": self._endpoint()}

    def _generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        # Constrained decoding: Ollama guarantees syntactically valid JSON, which
        # removes a whole failure class rather than patching the parser after the
        # fact. Without it a 3B model drifts to a PYTHON dict literal (single
        # quotes) and any possessive apostrophe in the narrative then terminates
        # the string early -- "Dr. R Mehta's report" turned a complete, correct
        # summary into a SyntaxError and an empty draft. English clinical prose is
        # full of possessives, so that is frequent, not a fluke.
        # Off-switch kept for engines/prompts that must return prose.
        if self.spec.get("json_mode", True):
            payload["format"] = "json"
        req = urllib.request.Request(
            self._handle["endpoint"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:  # pragma: no cover
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc
        return body.get("message", {}).get("content", "")

    def unload(self) -> None:
        # Ollama keeps the model in VRAM ~5 min after the last request (its
        # keep_alive default) — an empty chat with keep_alive=0 evicts it now,
        # so the next Transformers candidate gets the full 8 GB.
        if self._handle is not None:
            payload = {"model": self.model_id, "messages": [], "keep_alive": 0}
            req = urllib.request.Request(
                self._handle["endpoint"],
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
            except (urllib.error.URLError, OSError):  # pragma: no cover
                pass  # best effort; keep_alive will expire on its own
        super().unload()


register_adapter("ollama_llm", lambda logical_name, spec, env: OllamaAdapter(logical_name, spec, env))
