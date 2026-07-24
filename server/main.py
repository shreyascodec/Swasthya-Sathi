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

import mimetypes
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections import OrderedDict as OrderedDictType  # noqa: F401

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import models  # noqa: F401  (registers model adapters)
from core.context import SessionContext, UploadedFile
from core.pipeline import Pipeline, new_session
from stages import imaging

app = FastAPI(title="Swasthya Sathi API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# One shared pipeline (models are loaded/unloaded per stage inside it).
PIPELINE = Pipeline()
DATA_DIR = Path(PIPELINE.config.env.data_dir).resolve()


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


#: Live sessions, most-recently-created last. Capped so a kiosk running all day
#: cannot grow memory without bound — each session pins a full SessionContext
#: (audit log, summary, answers). The oldest are evicted once past the cap; a
#: patient interaction is short and single, so eviction never hits an active one.
SESSIONS: "OrderedDict[str, _Session]" = OrderedDict()
MAX_SESSIONS = 64


def _remember(s: _Session) -> None:
    SESSIONS[s.ctx.session_id] = s
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)  # evict oldest


def _sess(sid: str) -> _Session:
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, f"unknown session {sid}")
    return s


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
        engine = (c.ocr.engine if c.ocr else None) or "PaddleOCR"
        return [
            {"label": "Engine", "value": engine},
            {"label": "Model", "value": f"{spec.get('det_model')} + {spec.get('rec_model')}"},
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
        spoken_ms = sum(cl.duration_ms or 0 for cl in c.audio_out)
        return [
            {"label": "Engine", "value": engine},
            {"label": "Voice", "value": voice},
            {"label": "Device", "value": "CPU · GPU-free"},
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
        },
    }


# --- endpoints ---------------------------------------------------------------

class NewSessionBody(BaseModel):
    lang: str = "hi"


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "env": PIPELINE.config.env.name}


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
        s.ctx = PIPELINE.run_stage(stage.name, s.ctx)
        info["elapsed"] = round(time.time() - t0, 1)
        info["status"] = "done"
        info["note"] = _stage_note(stage.name, s.ctx)
        s.next_idx += 1

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
        info["elapsed"] = round(time.time() - t0, 1)
        info["status"] = "error"
        info["note"] = f"{type(e).__name__}: {e}"
        s.paused = {"kind": "error", "stage": stage.name,
                    "detail": f"{type(e).__name__}: {e}"}
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


# --- production UI -----------------------------------------------------------
# Serve the built SPA from this same process when `frontend/dist` exists, so a
# deployed kiosk is ONE origin and ONE command (`uvicorn server.main:app`) with
# no Vite dev server and no CORS. The frontend calls relative /api paths, which
# only resolve if the UI is served from the API origin — in dev that is Vite's
# proxy, in production it is this mount. Mounted last: "/" would otherwise
# shadow every /api route above.
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
