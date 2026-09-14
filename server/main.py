"""FastAPI backend for the React UI.

Thin HTTP wrapper around the EXISTING pipeline. It imports and drives
``core.pipeline.Pipeline`` exactly as the Streamlit app does — same stages, same
models, same OCR cache, same gates — so the React front end and the Streamlit
app are two faces of one unchanged engine. Nothing in core/ stages/ models/ is
modified; that is what guarantees the working flows keep working.

State model: one SessionContext per session_id, held in memory. Single kiosk
user, single uvicorn worker — no database needed for the POC. The frontend
drives the stage loop one call at a time (POST /run-stage), which mirrors
Streamlit's one-stage-per-rerun stepper.

Run:  uvicorn server.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import urllib.error
import urllib.request
import re
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections import OrderedDict as OrderedDictType  # noqa: F401

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

import models  # noqa: F401  (registers model adapters)
from core.context import SessionContext, UploadedFile
from core.model_manager import VRAMBudgetError
from core.pipeline import Pipeline, new_session
from server.config import ServerConfig
from server.logconf import configure_logging
from server.warmup import new_readiness, start_warmup_thread
from stages import imaging

APP_VERSION = "1.0.0"

CFG = ServerConfig.from_env()
configure_logging(CFG.log_level)
log = logging.getLogger("swasthya.server")

# One shared pipeline (models are loaded/unloaded per stage inside it).
PIPELINE = Pipeline()
DATA_DIR = Path(PIPELINE.config.env.data_dir).resolve()

# Single kiosk, single GPU: all pipeline work is serialized through this lock so
# warmup and two overlapping requests can never touch ModelManager at once.
PIPELINE_LOCK = threading.Lock()

# Warmup progress, published to GET /api/ready and mutated by the warmup thread.
READINESS = new_readiness()

# Reaper cadence — how often idle sessions (and their data dirs) are swept.
_REAP_INTERVAL_S = 120


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "starting Swasthya Sakhi v%s — env=%s device=%s data_dir=%s",
        APP_VERSION, PIPELINE.config.env.name, PIPELINE.config.env.device, DATA_DIR,
    )
    _sweep_orphan_dirs()  # crash recovery: drop stale session dirs from a prior run
    if CFG.warmup:
        start_warmup_thread(PIPELINE, PIPELINE_LOCK, READINESS)
    else:
        READINESS.update(ready=True, warming=False, seconds=0.0)
        log.info("warmup disabled (SS_WARMUP=0) — models load on first use")
    reaper = asyncio.create_task(_reaper_loop())
    try:
        yield
    finally:
        reaper.cancel()
        with PIPELINE_LOCK:
            PIPELINE.models.release_all()
        log.info("shutdown complete — models released")


app = FastAPI(title="Swasthya Sakhi API", version=APP_VERSION, lifespan=lifespan)
if CFG.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CFG.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    dt = (time.time() - t0) * 1000
    # Skip the noisy static/media chatter; log the API surface.
    if request.url.path.startswith("/api"):
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, dt)
    # Never cache the SPA HTML shell: it references hash-named JS/CSS, so a cached
    # shell pins an OLD bundle after a redeploy (a stale kiosk mid-demo). The
    # hashed assets themselves stay cacheable. Applied here so it covers the
    # StaticFiles(html=True) mount without touching it.
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def _err(status: int, type_: str, message: str, detail=None) -> JSONResponse:
    body: dict = {"error": {"type": type_, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(StarletteHTTPException)
async def _handle_http(request: Request, exc: StarletteHTTPException):
    return _err(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _handle_validation(request: Request, exc: RequestValidationError):
    return _err(422, "validation_error", "Invalid request.", detail=str(exc.errors()))


@app.exception_handler(VRAMBudgetError)
async def _handle_vram(request: Request, exc: VRAMBudgetError):
    log.error("VRAM budget exceeded: %s", exc)
    return _err(503, "model_unavailable", "The device is out of GPU memory for this model. Try again in a moment.")


@app.exception_handler(Exception)
async def _handle_unexpected(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return _err(500, "internal_error", "Something went wrong on the kiosk. Start a new session and try again.")


class _Session:
    """A live session: the flowing context + per-stage run bookkeeping."""

    def __init__(self, lang: str) -> None:
        self.ctx: SessionContext = new_session(lang=lang)
        self.stages = {
            s.name: {"status": "pending", "elapsed": None, "note": ""}
            for s in PIPELINE.stages
        }
        self.next_idx = 0
        self.paused: dict | None = None
        self.last_activity: float = time.time()


#: Live sessions, most-recently-created last. Capped so a kiosk running all day
#: cannot grow memory without bound — each session pins a full SessionContext
#: (audit log, summary, answers). The oldest are evicted once past the cap; a
#: patient interaction is short and single, so eviction never hits an active one.
SESSIONS: "OrderedDict[str, _Session]" = OrderedDict()

_SID_RE = re.compile(r"^[0-9a-f]{12}$")  # session ids are 12 hex chars (new_session)


def _session_dir(sid: str) -> Path:
    return DATA_DIR / sid


def _delete_session_dir(sid: str) -> None:
    """Remove a session's on-disk artifacts (uploads, audio, report). Privacy:
    a finished/abandoned patient must not linger on the kiosk."""
    d = _session_dir(sid)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        log.info("cleaned data dir for session %s", sid)


def _remember(s: _Session) -> None:
    SESSIONS[s.ctx.session_id] = s
    while len(SESSIONS) > CFG.max_sessions:
        old_sid, _ = SESSIONS.popitem(last=False)  # evict oldest
        _delete_session_dir(old_sid)


def _sess(sid: str) -> _Session:
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, f"unknown session {sid}")
    s.last_activity = time.time()
    SESSIONS.move_to_end(sid)  # keep LRU order honest so the reaper/cap are fair
    return s


# --- session lifecycle: idle reaper + crash-recovery sweep -------------------

def _reap_idle_sessions() -> None:
    cutoff = time.time() - CFG.session_ttl_seconds
    stale = [sid for sid, s in SESSIONS.items() if s.last_activity < cutoff]
    for sid in stale:
        SESSIONS.pop(sid, None)
        _delete_session_dir(sid)
    if stale:
        log.info("reaped %d idle session(s)", len(stale))


async def _reaper_loop() -> None:
    while True:
        await asyncio.sleep(_REAP_INTERVAL_S)
        try:
            _reap_idle_sessions()
        except Exception:  # noqa: BLE001 — a reaper crash must not kill the server
            log.exception("session reaper error")


def _sweep_orphan_dirs() -> None:
    """On startup, drop session data dirs left by a prior process that are older
    than the TTL. In-memory sessions never survive a restart, so any such dir is
    orphaned PHI."""
    if not DATA_DIR.is_dir():
        return
    cutoff = time.time() - CFG.session_ttl_seconds
    for d in DATA_DIR.iterdir():
        try:
            if d.is_dir() and _SID_RE.match(d.name) and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                log.info("swept orphan session dir %s", d.name)
        except OSError:
            continue


# --- friendly stage-error text + report persistence --------------------------

def _friendly_stage_error(stage_name: str, exc: Exception) -> str:
    """Operator-facing message for a stage crash. The raw exception stays in the
    server log and in the stage `note`; the banner gets guidance, not a traceback."""
    label = STAGE_TITLES.get(stage_name, stage_name)
    text = str(exc).lower()
    if isinstance(exc, VRAMBudgetError):
        return f"“{label}” could not load its model — the device is out of GPU memory. Retry in a moment, or restart the kiosk."
    if "connection" in text or "connect" in text or "ollama" in text:
        return f"“{label}” could not reach its model service (is Ollama running?). Retry, or stop and start over."
    if "not found" in text or "no such file" in text or "missing" in text:
        return f"“{label}” is missing a required model file on this device. Stop and check the install."
    return f"The “{label}” step failed and the run was halted. Retry the step, or stop and start a new session."


# Human labels for stages, used in friendly errors and pause banners.
STAGE_TITLES = {
    "intake": "Intake & image quality", "ocr": "Text extraction (OCR)",
    "image_tag": "Image tagging", "summary": "Report summary",
    "interpret": "Lab interpretation", "intake_qa": "Intake questions",
    "voice": "Voice generation", "hashing": "Integrity hashing", "report": "Final report",
}


def _persist_report(s: _Session) -> None:
    """Write the sealed report as report_v<n>.json into the session data dir — a
    durable, PHI-free-audit-adjacent artifact without standing up a database."""
    if not (CFG.persist_reports and s.ctx.report):
        return
    rep = s.ctx.report
    d = _session_dir(s.ctx.session_id)
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": s.ctx.session_id,
        "version": rep.version,
        "sha256": rep.sha256,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "content": rep.content,
    }
    try:
        (d / f"report_v{rep.version}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("persisted report v%s for session %s", rep.version, s.ctx.session_id)
    except OSError as e:
        log.warning("could not persist report for %s: %s", s.ctx.session_id, e)


# --- derived views (mirror the Streamlit renderers) --------------------------

def _display_name(u: UploadedFile) -> str:
    """The filename the patient/operator actually recognises.

    ``u.path`` is the canonical *processed* artifact ("8f5a52ee_p0.jpg"), which
    is meaningless in a "please re-scan X" prompt — the operator is holding a
    document they know by its original name. Prefer the original upload and
    strip the collision-avoiding id prefix this server added at upload time.
    """
    name = Path(u.source_path or u.path).name
    prefix = f"{u.id}_"
    return name[len(prefix):] if name.startswith(prefix) else name


def _summary_parse_error(c: SessionContext) -> str | None:
    if c.summary is None:
        return None
    for u in c.summary.content.get("unknowns", []):
        if isinstance(u, str) and u.startswith("parse_error"):
            return u
    return None


def _looks_like_report(c: SessionContext) -> bool:
    """Whether the summary extracted anything clinical — at least one lab value
    or a named medication. The gate for the 'not a lab report' guardrail; kept
    here (not just in the intake_qa rules) so a non-report is halted BEFORE the
    interview stages ever run, not merely left question-less."""
    content = c.summary.content if c.summary else {}
    return bool(content.get("lab_findings") or content.get("medications"))


def _stage_note(name: str, c: SessionContext) -> str:
    if name == "intake":
        flagged = sum(1 for u in c.uploads if u.needs_rescan)
        note = f"{len(c.uploads)} file(s) preprocessed"
        return note + (f", {flagged} flagged for rescan" if flagged else "")
    if name == "ocr" and c.ocr:
        return f"{len(c.ocr.fields)} fields extracted · {c.ocr.engine}"
    if name == "image_tag":
        return f"{len(c.image_tags)} image(s) tagged"
    if name == "summary" and c.summary:
        if _summary_parse_error(c):
            return f"⚠ LLM output not valid JSON — draft v{c.summary.version} is empty"
        return f"report draft v{c.summary.version}"
    if name == "interpret":
        hi = sum(1 for f in c.interpretations if f.high_priority)
        return f"{len(c.interpretations)} lab flag(s)" + (f", {hi} high-priority" if hi else "")
    if name == "intake_qa":
        return f"{len(c.questions)} question(s), {len(c.answers)} answer(s)"
    if name == "voice":
        return f"{len(c.audio_out)} audio clip(s)"
    if name == "hashing":
        hashed = sum(1 for u in c.uploads if u.sha256)
        return f"{hashed} file(s) hashed" + (" · report stamped" if c.report and c.report.sha256 else "")
    if name == "report" and c.report:
        return f"report v{c.report.version}"
    return ""


def _dev_label(spec: dict) -> str:
    """Human 'GPU · fp16' / 'CPU' from a model spec (device + precision knob)."""
    d = str(spec.get("device", "cpu"))
    base = "GPU" if d == "cuda" else d.upper()
    prec = spec.get("precision") or spec.get("compute") or spec.get("quant")
    return f"{base} · {prec}" if prec else base


def _stage_metrics(name: str, c: SessionContext) -> list[dict]:
    """Stakeholder-facing parameters for a completed stage: which model, on what
    device/precision, and what it produced. Rendered as a horizontal strip under
    the stage as soon as it finishes. Counts come from the live context (what
    actually happened); model identity comes from the deployed config.

    Each item: {label, value, kind?} where kind ∈ {ok, flag} tints the chip.
    """
    M = PIPELINE.config.models

    if name == "intake":
        flagged = sum(1 for u in c.uploads if u.needs_rescan)
        return [
            {"label": "Engine", "value": "OpenCV · deskew + denoise"},
            {"label": "Compute", "value": "CPU · ARM-ready"},
            {"label": "Files", "value": str(len(c.uploads))},
            {"label": "Flagged for rescan", "value": str(flagged),
             "kind": "flag" if flagged else "ok"},
        ]
    if name == "ocr":
        spec = M["ocr"]["primary"]
        engine = (c.ocr.engine if c.ocr else None) or spec.get("impl") or "rapidocr"
        model_bits = [spec.get("det_model"), spec.get("rec_model")]
        model_label = " + ".join(b for b in model_bits if b) or str(spec.get("impl") or engine)
        return [
            {"label": "Engine", "value": engine},
            {"label": "Model", "value": model_label},
            {"label": "Device", "value": _dev_label(spec)},
            {"label": "Fields extracted", "value": str(len(c.ocr.fields) if c.ocr else 0)},
        ]
    if name == "image_tag":
        spec = M["image_tag"]["primary"]
        skipped = sum(1 for u in c.uploads if u.is_document)
        return [
            {"label": "Model", "value": "MobileNetV3-Small · 4-class head"},
            {"label": "Device", "value": _dev_label(spec)},
            {"label": "Clinical images tagged", "value": str(len(c.image_tags))},
            {"label": "Report pages skipped", "value": str(skipped)},
        ]
    if name == "summary":
        spec = M["llm"]["primary"]
        out = [
            {"label": "Model", "value": spec.get("model", spec.get("impl", "?"))},
            {"label": "Runtime", "value": f"{spec.get('runtime', '')} · {spec.get('quant', '')}".strip(" ·")},
            {"label": "Device", "value": "GPU" if spec.get("device") == "cuda" else str(spec.get("device", "cpu")).upper()},
            {"label": "Draft", "value": f"v{c.summary.version}" if c.summary else "—"},
        ]
        f = _faithfulness(c)
        if f:
            out.append({"label": "Faithfulness",
                        "value": f"{round(f['score'] * 100)}%",
                        "kind": "ok" if f["ok"] else "flag"})
        return out
    if name == "interpret":
        hi = sum(1 for f in c.interpretations if f.high_priority)
        return [
            {"label": "Method", "value": "Reference-range rules · no diagnosis"},
            {"label": "Lab flags", "value": str(len(c.interpretations))},
            {"label": "High-priority", "value": str(hi), "kind": "flag" if hi else "ok"},
            {"label": "Recovered analytes", "value": str(len(_recovered_analytes(c)))},
        ]
    if name == "intake_qa":
        return [
            {"label": "Method", "value": "Condition-matched templates"},
            {"label": "Language", "value": c.lang},
            {"label": "Questions generated", "value": str(len(c.questions))},
            {"label": "Answers captured", "value": str(len(c.answers))},
        ]
    if name == "voice":
        spec = M["tts_en" if c.lang == "en" else "tts"]["primary"]
        impl = spec.get("impl", "")
        engine = {"kokoro": "Kokoro-82M (Apache-2.0)",
                  "piper": "Piper · VITS/ONNX",
                  "stub_tts": "silent stub"}.get(impl, impl)
        voice = spec.get("voice", "")
        voice = Path(str(voice)).stem if str(voice).endswith(".onnx") else str(voice) or "—"
        # Realtime factor is MEASURED from this session, not asserted. The old
        # hardcoded "~0.03 (≈30× realtime)" was a Piper-era figure that survived
        # the Kokoro swap; bench/runner_tts.py measures Kokoro at mean RTF 0.29,
        # so the chip was overstating synthesis speed ~10x to stakeholders.
        #
        # Device is read from the spec for the same reason: it was hardcoded
        # "CPU · GPU-free", which went stale the moment Hindi moved to cuda.
        spoken_ms = sum(cl.duration_ms or 0 for cl in c.audio_out)
        return [
            {"label": "Engine", "value": engine},
            {"label": "Voice", "value": voice},
            {"label": "Device", "value": _dev_label(spec)},
            {"label": "Audio synthesised", "value": f"{spoken_ms / 1000:.1f} s"},
            {"label": "Clips synthesised", "value": str(len(c.audio_out))},
        ]
    if name == "hashing":
        hashed = sum(1 for u in c.uploads if u.sha256)
        sealed = bool(c.report and c.report.sha256)
        return [
            {"label": "Algorithm", "value": "SHA-256"},
            {"label": "Source files hashed", "value": str(hashed)},
            {"label": "Manifest digest", "value": "computed" if hashed else "—",
             "kind": "ok" if hashed else None},
            {"label": "Report stamped", "value": "yes" if sealed else "pending",
             "kind": "ok" if sealed else None},
        ]
    if name == "report":
        digest = (c.report.sha256[:12] + "…") if (c.report and c.report.sha256) else "—"
        return [
            {"label": "Assembler", "value": "Deterministic · versioned"},
            {"label": "Version", "value": f"v{c.report.version}" if c.report else "—"},
            {"label": "Content digest", "value": digest},
            {"label": "Audit", "value": "PHI-free · type/version only", "kind": "ok"},
        ]
    return []


def _recovered_analytes(c: SessionContext) -> list[str]:
    if not (c.summary and c.interpretations):
        return []
    findings = c.summary.content.get("lab_findings") or []
    if not findings:
        return []

    def key(n: str) -> str:
        return "".join(ch for ch in str(n).lower() if ch.isalnum())

    in_summary = {key(f.get("analyte", "")) for f in findings}
    return [f.analyte for f in c.interpretations if key(f.analyte) not in in_summary]


def _faithfulness(c: SessionContext) -> dict | None:
    if c.summary is None:
        return None
    from stages.faithfulness import check_faithfulness
    from stages.summary_schema import SummarySchema

    content = SummarySchema.model_validate(c.summary.content)
    rep = check_faithfulness(content, c.ocr.fields if c.ocr else [])
    return {
        "score": rep.faithfulness,
        "ok": rep.ok,
        "parse_error": _summary_parse_error(c),
        "issues": [i.detail for i in rep.issues[:8]],
    }


def _snapshot(sid: str) -> dict:
    s = _sess(sid)
    c = s.ctx
    return {
        "session_id": c.session_id,
        "lang": c.lang,
        "env": PIPELINE.config.env.name,
        "device": PIPELINE.config.env.device,
        "stages": [
            {"name": st.name, "order": st.order, "description": st.description,
             **s.stages[st.name],
             # Recompute the note from the LIVE context for completed stages.
             # It was frozen at stage-run time, so intake_qa kept reporting
             # "0 answer(s)" no matter how many answers the patient then gave at
             # the Q&A gate — which runs after that stage completes. An "error"
             # note holds the exception text and must survive untouched.
             **({"note": _stage_note(st.name, c)}
                if s.stages[st.name]["status"] in ("done", "flagged") else {}),
             "metrics": _stage_metrics(st.name, c)
             if s.stages[st.name]["status"] in ("done", "flagged") else []}
            for st in PIPELINE.stages
        ],
        "next_idx": s.next_idx,
        "total_stages": len(PIPELINE.stages),
        "paused": s.paused,
        "done": s.next_idx >= len(PIPELINE.stages),
        "ctx": c.model_dump(mode="json"),
        "derived": {
            "faithfulness": _faithfulness(c),
            "recovered": _recovered_analytes(c),
            "narrative_review": (c.summary.content.get("narrative_review") if c.summary else None) or [],
            # MCH maternal mode: risk tier + reasons + action (None in lab mode).
            "maternal_risk": (c.summary.content.get("maternal_risk") if c.summary else None),
        },
    }


# --- endpoints ---------------------------------------------------------------

class NewSessionBody(BaseModel):
    lang: str = "hi"


@app.get("/api/health")
def health() -> dict:
    """Liveness — the process is up and serving. Answers immediately, even while
    models are still warming."""
    return {"ok": True, "version": APP_VERSION, "env": PIPELINE.config.env.name,
            "device": PIPELINE.config.env.device}


@app.get("/api/ready")
def ready() -> dict:
    """Readiness — have the models been warmed? The kiosk UI holds the Process
    button until this reports ready, so the first patient isn't hit with cold
    model loads."""
    return {
        "ready": READINESS["ready"],
        "warming": READINESS["warming"],
        "loaded": READINESS["loaded"],
        "unavailable": READINESS["unavailable"],
        "seconds": READINESS["seconds"],
        "sessions": len(SESSIONS),
    }


class AvatarTTSBody(BaseModel):
    text: str
    lang: str = "hi"


@app.post("/api/avatar/tts")
def avatar_tts(body: AvatarTTSBody) -> dict:
    """Speak ``text`` with the pipeline's own TTS (Hindi Kokoro / English Piper)
    and return audio + a phoneme timeline for the 3D avatar's lip-sync.

    Response shape matches the avatar's expected TTS contract:
      { audio_base64, sample_rate, audio_duration, alignment: {characters,
        character_start_times_seconds, character_end_times_seconds} }
    Reuses the same warmed voice as the kiosk — no second TTS server, offline.
    """
    import base64

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    lang = (body.lang or "hi").strip() or "hi"
    logical = "tts_en" if (lang == "en" and "tts_en" in PIPELINE.config.models) else "tts"

    with PIPELINE_LOCK:  # serialize against warmup / stage runs (single GPU)
        tts = PIPELINE.models.get(logical)
        audio, timeline = tts.synthesize_aligned(text, lang=lang)

    chars, starts, ends = [], [], []
    for e in timeline or []:
        chars.append(e["phoneme"])
        starts.append(round(e["start"], 4))
        ends.append(round(e["end"], 4))
    alignment = {
        "characters": chars,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }
    return {
        "audio_base64": base64.b64encode(audio.data).decode(),
        "sample_rate": audio.sample_rate,
        "audio_duration": (audio.duration_ms or 0) / 1000.0,
        "voice": logical,
        "normalized_alignment": alignment,
        "alignment": alignment,
    }


@app.post("/api/avatar/smoke-clip")
def avatar_smoke_clip(body: AvatarTTSBody) -> dict:
    """Phase-B browser smoke: write one Stage-[7]-shaped clip under data_dir and
    return ``{path, alignment}`` so the UI can exercise ``speakClip`` (file
    fetch + lip-sync) without running the full pipeline.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    lang = (body.lang or "hi").strip() or "hi"
    logical = "tts_en" if (lang == "en" and "tts_en" in PIPELINE.config.models) else "tts"

    with PIPELINE_LOCK:
        tts = PIPELINE.models.get(logical)
        audio, timeline = tts.synthesize_aligned(text, lang=lang)

    out_dir = DATA_DIR / "_avatar_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"smoke_{lang}.wav"
    path.write_bytes(audio.data)
    return {
        "path": str(path),
        "alignment": timeline or [],
        "audio_duration": (audio.duration_ms or 0) / 1000.0,
        "sample_rate": audio.sample_rate,
        "voice": logical,
    }


# --- Brenin/Tavus avatar proxy -----------------------------------------------
# The kiosk drives a live talking-head avatar, but the Brenin API key must NEVER
# reach the browser. These endpoints hold the key server-side (env) and expose
# only what the client needs: a short-lived session_token to render the SDK, a
# say() proxy to speak our fixed pipeline lines (echo mode — bypasses the
# avatar's own LLM, preserving the no-ad-lib safety invariant), and end() to stop
# per-second billing. Config via env: SS_BRENIN_API_KEY, SS_BRENIN_AVATAR_ID,
# SS_BRENIN_BASE (default https://uat.brenin.co).
_BRENIN_BASE = os.environ.get("SS_BRENIN_BASE", "https://uat.brenin.co").rstrip("/")
_BRENIN_KEY = os.environ.get("SS_BRENIN_API_KEY", "")
_BRENIN_AVATAR = os.environ.get("SS_BRENIN_AVATAR_ID", "")


def _brenin_call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        _BRENIN_BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", "x-api-key": _BRENIN_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise HTTPException(502, f"avatar upstream {e.code}: {body}")
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"avatar upstream unreachable: {e}")


def _brenin_session_fields(d: dict) -> tuple[str | None, str | None, str | None]:
    """Normalize Brenin create-conversation ids (snake_case or camelCase / nested)."""
    sess = d.get("session") if isinstance(d.get("session"), dict) else {}
    av = d.get("avatar") if isinstance(d.get("avatar"), dict) else {}
    sid = (
        d.get("session_id")
        or d.get("conversation_id")
        or d.get("conversationId")
        or sess.get("session_id")
        or sess.get("id")
    )
    token = (
        d.get("session_token")
        or d.get("sessionToken")
        or sess.get("sessionToken")
        or sess.get("session_token")
    )
    avatar = d.get("avatar_id") or d.get("avatarId") or av.get("avatar_id") or av.get("id") or av.get("avatarId")
    return (str(sid) if sid else None, str(token) if token else None, str(avatar) if avatar else None)


# Maternal-health identity, so ANY autonomous speech (should be none in echo mode)
# stays on-domain — never the avatar's stock sales persona.
_MCH_SYSTEM_PROMPT = (
    "You are Swasthya Sakhi, a warm, respectful maternal and child health companion "
    "for pregnant women at a rural health kiosk in India. You ONLY read aloud the exact "
    "lines you are given. You never sell anything, never diagnose, never start a topic, "
    "and never mention any product or business. If addressed directly, reply briefly and "
    "only about maternal health and using this kiosk."
)
_MCH_CONTEXT = (
    "Maternal & child health risk-screening kiosk. Echo mode: speak only the provided lines."
)


class AvatarSessionBody(BaseModel):
    greeting: str | None = None
    system_prompt: str | None = None
    languages: list[str] | None = None
    language: str | None = None
    conversational_context: str | None = None


@app.post("/api/avatar/session")
def avatar_session(body: AvatarSessionBody) -> dict:
    """Create a live avatar session. Returns ONLY the session_token/id — never the key."""
    if not _BRENIN_KEY or not _BRENIN_AVATAR:
        raise HTTPException(503, "avatar not configured (set SS_BRENIN_API_KEY / SS_BRENIN_AVATAR_ID)")
    # Sticky kiosk language: speak ONLY the selected language until the patient
    # toggles. Do not default in both hi+en — Phoenix then often greets in English.
    # greeting MUST be sent even when empty: omitting the field makes Brenin play
    # the PAL connect greeting (English "Hello! How can I assist you today?").
    # `if body.greeting:` would drop "" because empty string is falsy.
    primary = (body.language or "hi").strip().lower()
    if primary not in {"hi", "en"}:
        primary = "hi"
    langs = list(body.languages) if body.languages else [primary]
    langs = [x.strip().lower() for x in langs if x and x.strip()]
    if primary not in langs:
        langs = [primary] + langs
    greeting = "" if body.greeting is None else body.greeting
    payload: dict = {
        "avatar_id": _BRENIN_AVATAR,
        "conversation_name": "Swasthya Sakhi",
        "background": "transparent",
        "system_prompt": body.system_prompt or _MCH_SYSTEM_PROMPT,
        "conversational_context": body.conversational_context or _MCH_CONTEXT,
        "languages": langs,
        "language": primary,
        "greeting": greeting,
        "properties": {"max_call_duration": 900},
    }
    d = _brenin_call("POST", "/api-b-v1/brenin/conversations", payload).get("data", {})
    sid, token, avatar = _brenin_session_fields(d if isinstance(d, dict) else {})
    if not sid or not token:
        raise HTTPException(502, "avatar session missing id/token")
    return {
        "session_id": sid,
        "session_token": token,
        "avatar_id": avatar or _BRENIN_AVATAR,
        "base": _BRENIN_BASE,
    }


@app.get("/api/avatar/info")
def avatar_info() -> dict:
    """Avatar thumbnail (for the Welcome poster) — lets the kiosk show the face
    without a billable live session while idle."""
    if not _BRENIN_KEY or not _BRENIN_AVATAR:
        return {"thumbnail": None}
    try:
        d = _brenin_call("GET", f"/api-b-v1/brenin/avatars/{_BRENIN_AVATAR}").get("data", {})
    except HTTPException:
        return {"thumbnail": None}
    return {"thumbnail": d.get("thumbnail_url") or d.get("thumbnailUrl"), "name": d.get("name")}


class AvatarSayBody(BaseModel):
    session_id: str
    text: str
    session_token: str | None = None


@app.post("/api/avatar/say")
def avatar_say(body: AvatarSayBody) -> dict:
    """Echo a fixed line. Prefer the SDK WebRTC path on the kiosk; this is fallback.

    Brenin's SDK posts `/conversations/{session_token}/say` with `mode=echo`.
    Create-conversation also returns `session_id` — try both.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    payload = {"text": text, "mode": "echo"}
    keys = [k for k in (body.session_id, body.session_token) if k]
    last_err: HTTPException | None = None
    for key in keys:
        try:
            return _brenin_call("POST", f"/api-b-v1/brenin/conversations/{key}/say", payload)
        except HTTPException as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    raise HTTPException(400, "session_id is empty")


class AvatarEndBody(BaseModel):
    session_id: str


@app.post("/api/avatar/end")
def avatar_end(body: AvatarEndBody) -> dict:
    """End the session to stop per-second billing."""
    return _brenin_call("POST", f"/api-b-v1/brenin/conversations/{body.session_id}/end", {})


@app.post("/api/session")
def create_session(body: NewSessionBody) -> dict:
    s = _Session(body.lang)
    _remember(s)
    return _snapshot(s.ctx.session_id)


@app.get("/api/session/{sid}")
def get_session(sid: str) -> dict:
    return _snapshot(sid)


@app.post("/api/session/{sid}/upload")
async def upload(sid: str, files: list[UploadFile] = File(...)) -> dict:
    s = _sess(sid)
    raw_dir = DATA_DIR / s.ctx.session_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        uid = uuid.uuid4().hex[:8]
        dest = raw_dir / f"{uid}_{f.filename}"
        dest.write_bytes(await f.read())
        s.ctx.uploads.append(UploadedFile(
            id=uid, path=str(dest), source_path=str(dest),
            type=imaging.guess_type(dest),
        ))
    return _snapshot(sid)


@app.post("/api/session/{sid}/run-stage")
def run_stage(sid: str) -> dict:
    """Run the next pending stage. The frontend calls this in a loop until the
    snapshot reports done or paused — same shape as Streamlit's stepper."""
    s = _sess(sid)
    if s.paused is not None:
        raise HTTPException(409, "run is paused; resolve the pause first")
    if s.next_idx >= len(PIPELINE.stages):
        return _snapshot(sid)
    if not s.ctx.uploads:
        raise HTTPException(400, "upload at least one file first")

    stage = PIPELINE.stages[s.next_idx]
    info = s.stages[stage.name]
    t0 = time.time()
    try:
        with PIPELINE_LOCK:  # single GPU / single worker: serialize all stage runs
            s.ctx = PIPELINE.run_stage(stage.name, s.ctx)
        info["elapsed"] = round(time.time() - t0, 1)
        info["status"] = "done"
        info["note"] = _stage_note(stage.name, s.ctx)
        s.next_idx += 1
        if stage.name == "report":
            _persist_report(s)

        # Gate: hold after [7] voice for the live intake Q&A. Voice is what
        # synthesises the question audio, so the Q&A cannot run earlier and still
        # speak; hashing/report run only after the patient answers, so the sealed
        # report includes the answers.
        if stage.name == "voice" and s.ctx.questions:
            s.paused = {
                "kind": "intake_qa", "stage": "voice",
                "detail": "Answer the intake questions with the patient, then "
                          "continue — hashing and the report run last so the "
                          "answers are included in what gets sealed.",
            }

        # Gate: summary produced unusable JSON.
        if stage.name == "summary" and _summary_parse_error(s.ctx):
            info["status"] = "flagged"
            s.paused = {
                "kind": "flag", "stage": "summary",
                "detail": "The LLM did not return valid JSON, so the report draft "
                          "is empty. Continue (later stages run on an empty summary) "
                          "or stop and retry with another model.",
            }
        # Gate: the upload is not a recognisable lab/medical report. STRICT — a
        # non-medical document (a software doc, an invoice) or an unreadable scan
        # must not be carried into interpretation and a spoken patient interview.
        # Runs only if the summary parsed cleanly (else the parse-error gate above
        # already owns the pause) and nothing yielded a lab value or medication.
        if stage.name == "summary" and s.paused is None and not _looks_like_report(s.ctx):
            info["status"] = "flagged"
            s.paused = {
                "kind": "not_a_report", "stage": "summary",
                "detail": "This does not look like a lab report — no recognised "
                          "test values or medications were found. Please check the "
                          "uploaded document. Stop and re-upload the correct report, "
                          "or continue only if you are certain this is a valid report "
                          "the reader misread.",
            }
        # Gate: an uploaded page failed the quality check.
        if stage.name == "intake":
            bad = [u for u in s.ctx.uploads if u.needs_rescan]
            if bad:
                info["status"] = "flagged"
                s.paused = {
                    "kind": "flag", "stage": "intake",
                    "detail": f"{len(bad)} file(s) failed the quality gate and "
                              "should be re-scanned: "
                              + ", ".join(_display_name(u) for u in bad),
                }
    except Exception as e:  # noqa: BLE001
        log.exception("stage '%s' failed for session %s", stage.name, sid)
        info["elapsed"] = round(time.time() - t0, 1)
        info["status"] = "error"
        info["note"] = f"{type(e).__name__}: {e}"  # technical detail kept for the operator panel
        s.paused = {"kind": "error", "stage": stage.name,
                    "detail": _friendly_stage_error(stage.name, e)}
    return _snapshot(sid)


class ResumeBody(BaseModel):
    action: str  # "continue" | "stop" | "retry"


@app.post("/api/session/{sid}/resume")
def resume(sid: str, body: ResumeBody) -> dict:
    """Resolve a pause: continue past it, retry the flagged stage, or stop."""
    s = _sess(sid)
    if s.paused is None:
        return _snapshot(sid)
    stage = s.paused["stage"]
    if body.action == "continue":
        s.paused = None
    elif body.action == "retry":
        s.stages[stage]["status"] = "pending"
        # rewind so the flagged stage runs again next
        s.next_idx = next(i for i, st in enumerate(PIPELINE.stages) if st.name == stage)
        s.paused = None
    elif body.action == "stop":
        s.paused = None
        s.next_idx = len(PIPELINE.stages)  # halt
    return _snapshot(sid)


@app.post("/api/session/{sid}/answer")
async def answer(sid: str, question_id: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Transcribe a recorded intake answer and attach it (STT via the pipeline).

    capture_answer replaces on re-record, so answering a question twice keeps
    only the latest take — same as the Streamlit path.
    """
    s = _sess(sid)
    if not any(q.id == question_id for q in s.ctx.questions):
        raise HTTPException(404, "unknown question")
    stage = PIPELINE.stage_by_name("intake_qa")
    idx = next(i for i, q in enumerate(s.ctx.questions) if q.id == question_id)
    audio_dir = DATA_DIR / s.ctx.session_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "answer.webm").suffix or ".webm"
    dest = audio_dir / f"{idx:02d}_answer{ext}"
    dest.write_bytes(await file.read())
    with PIPELINE_LOCK:  # capture_answer runs STT — serialize against stage runs/warmup
        stage.capture_answer(s.ctx, question_id, str(dest))
    return _snapshot(sid)


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 64 * 1024

#: Pinned so playback does not depend on the host. On Windows mimetypes reads
#: the registry, where .wav is commonly mapped to audio/x-wav (or missing) —
#: Chrome is far happier with the canonical types for the media we emit.
_MEDIA_TYPES = {
    ".wav": "audio/wav", ".webm": "audio/webm", ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}


def _media_type(p: Path) -> str:
    return (_MEDIA_TYPES.get(p.suffix.lower())
            or mimetypes.guess_type(p.name)[0]
            or "application/octet-stream")


def _ranged_response(p: Path, media_type: str, range_header: str) -> Response:
    """Honour a single HTTP Range request with a 206.

    Required for audio playback: Chrome's media loader opens every <audio> src
    with `Range: bytes=0-`. Starlette 0.37's FileResponse ignores Range and
    answers a bare 200 with no Accept-Ranges, and Chrome's media stack then
    stalls at readyState 0 — the WAV is fine and fetch() reads it, but the
    element never fires loadedmetadata, so the kiosk plays no question audio at
    all. Serving 206 + Content-Range fixes playback and gives seeking for free.
    """
    size = p.stat().st_size
    m = _RANGE_RE.match(range_header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return Response(status_code=416, headers={"content-range": f"bytes */{size}"})

    if m.group(1):                      # bytes=START-[END]
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    else:                               # bytes=-SUFFIX (trailing N bytes)
        start = max(size - int(m.group(2)), 0)
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416, headers={"content-range": f"bytes */{size}"})

    def body():
        remaining = end - start + 1
        with p.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        body(), status_code=206, media_type=media_type,
        headers={
            "content-range": f"bytes {start}-{end}/{size}",
            "content-length": str(end - start + 1),
            "accept-ranges": "bytes",
        },
    )


@app.get("/api/file")
def serve_file(path: str, request: Request) -> Response:
    """Serve a preview/audio artifact by path, confined to the session data dir."""
    p = Path(path).resolve()
    if not (p == DATA_DIR or DATA_DIR in p.parents):
        raise HTTPException(403, "path outside data dir")
    if not p.is_file():
        raise HTTPException(404, "not found")

    media_type = _media_type(p)
    range_header = request.headers.get("range")
    if range_header:
        return _ranged_response(p, media_type, range_header)
    # No Range: still advertise support so the media loader knows it can seek.
    return FileResponse(p, media_type=media_type, headers={"accept-ranges": "bytes"})


# --- 3D avatar assets: serve with caching disabled ---------------------------
# StaticFiles / Vite can answer a browser revalidation with 304 Not Modified.
# three.js's GLTFLoader mishandles that 304 — it surfaces the empty body as
# "Failed to load buffer Brenin.bin" and the avatar never renders (only the
# backdrop shows). Serving mesh/anims/textures with Cache-Control: no-store and
# no ETag means the browser never revalidates, so every request is a full 200.
# Assets are ~5 MB and local, so re-fetching per load is free.
#
# Canonical URL: /avatar/characters/... (must not collide with SPA /assets/*).
# Look under dist first (production), then frontend/public (dev / no-dist).
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
_DIST = _FRONTEND / "dist"
_AVATAR_CANDIDATES = [
    (_DIST / "avatar" / "characters").resolve(),
    (_DIST / "assets" / "characters").resolve(),          # legacy path
    (_FRONTEND / "public" / "avatar" / "characters").resolve(),
    (_FRONTEND / "public" / "assets" / "characters").resolve(),
]
_AVATAR_MEDIA = {
    ".gltf": "model/gltf+json", ".glb": "model/gltf-binary",
    ".buf": "application/octet-stream", ".bin": "application/octet-stream",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
}


def _avatar_file(sub: str) -> Path | None:
    for root in _AVATAR_CANDIDATES:
        if not root.is_dir():
            continue
        p = (root / sub).resolve()
        if str(p).startswith(str(root)) and p.is_file():
            return p
    return None


@app.get("/avatar/characters/{sub:path}")
def avatar_asset(sub: str) -> Response:
    p = _avatar_file(sub)
    if p is None:
        raise HTTPException(404, "not found")
    media = _AVATAR_MEDIA.get(p.suffix.lower(), "application/octet-stream")
    return Response(content=p.read_bytes(), media_type=media,
                    headers={"Cache-Control": "no-store"})


# --- production UI -----------------------------------------------------------
# Serve the built SPA from this same process when `frontend/dist` exists, so a
# deployed kiosk is ONE origin and ONE command (`uvicorn server.main:app`) with
# no Vite dev server and no CORS. The frontend calls relative /api paths, which
# only resolve if the UI is served from the API origin — in dev that is Vite's
# proxy, in production it is this mount. Mounted last: "/" would otherwise
# shadow every /api route above.
if _DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
