# Swasthya Sathi — Pipeline POC (React)

A React + FastAPI app that runs the full Swasthya Sathi pipeline end-to-end —
report intake → OCR → image tagging → structured summary → interpretation →
intake Q&A → spoken output → versioned **स्वास्थ्य साथी रिपोर्ट**. The React UI
(`frontend/`) drives the pipeline over an HTTP backend (`server/`) that wraps the
same stages the tests exercise.

Read `REACT_UI.md` (the UI + how to run it), `ARCHITECTURE.md` (design), and
`PLAN.md` (phase order).

## Core ideas

- **Stage-by-stage.** Each stage is solid before the next is built.
- **Model-swappable via config.** Every stage reads its model from
  `config/models.yaml`; swapping a model is a YAML edit, never a code change.
- **Three environments, one codebase.** `dev_4060` (RTX 4060 8 GB) → `cloud` →
  `orin` (Jetson Orin NX 16 GB ARM). Selected via `SS_ENV`; profiles live in
  `config/env/`. Code to the intersection: 8 GB VRAM ceiling, ARM-compatible,
  offline-first.
- **8 GB VRAM discipline.** `ModelManager` loads on demand and unloads to free
  VRAM; on `dev_4060` only one heavy GPU model is resident at a time.

## Layout

```
core/      Stage ABC, SessionContext, ModelManager, EnvProfile, Pipeline
stages/    s1..s9 pipeline stages
models/    model adapters + weights/ (STT/TTS/imagetag checkpoints)
config/    models.yaml (bench-swap here) + env/{dev_4060,cloud,orin}.yaml
db/        SQLite schema + repository (swappable to Postgres)
data/      labqar/ (ranges) + question_bank/ (intake patterns) + eval sets
server/    FastAPI backend wrapping the pipeline (the React UI's API)
frontend/  React + Vite app (the UI)
tests/     acceptance tests + per-stage harness
bench/     model bench harness + results
```

## Run

Easiest — double-click **`start_react.bat`** (opens the API on :8000 and the web
UI on :5173), then browse to **http://localhost:5173**. Full detail in
`REACT_UI.md`.

Manual:

```bash
pip install -r requirements.txt      # first time (fastapi, uvicorn, torch, …)

# terminal 1 — backend
python -m uvicorn server.main:app --port 8000

# terminal 2 — frontend
cd frontend
npm install                          # first time only
npm run dev                          # http://localhost:5173
```

The summary stage uses a local Ollama model (`phi3.5:3.8b`) — have the
Ollama app running (`ollama pull phi3.5:3.8b`). OCR is RapidOCR (ONNX).
STT/TTS run offline from `models/weights/` and the HF cache.

## Test / bench a single stage

```bash
pytest                          # acceptance tests
python -m tests.harness --list  # list stage names
python -m tests.harness ocr     # run one stage against the fixture context
```

## Environment switch (no code change)

The active profile is chosen via `SS_ENV` (defaults to `dev_4060`); profiles live
in `config/env/`. Set `SS_ENV=cloud` or `SS_ENV=orin` before launching the
backend.
