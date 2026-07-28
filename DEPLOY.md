# Deploying Swasthya Sathi (kiosk)

The kiosk is **one self-contained box**: the FastAPI server, the models (OCR, the
Ollama summary LLM, Kokoro voice), and the Chrome window all run on the same
machine. The server serves the built SPA **and** the API from a single origin on
`:8000`, so there is no second port and no CORS in production.

```
 Chrome (localhost:8000)  ──►  FastAPI (server.main:app)  ──►  Pipeline
                               serves frontend/dist at "/"      core/ stages/ models/  (unchanged)
                               API at /api
```

## 1. Build the UI (once per release)

```bash
cd frontend && npm ci && npm run build && cd ..
```

This produces `frontend/dist`, which `server/main.py` mounts at `/`.

## 2. Configuration

Server settings come from `SS_`-prefixed environment variables (copy
`.env.example` → `.env`, or set them in the service unit). The **hardware profile**
is separate — chosen by `SS_ENV` (`dev_4060` | `cloud` | `orin`, backed by
`config/env/<name>.yaml`).

| Var | Default | Purpose |
|-----|---------|---------|
| `SS_ENV` | `dev_4060` | engine/hardware profile |
| `SS_HOST` / `SS_PORT` | `127.0.0.1` / `8000` | bind address |
| `SS_ALLOWED_ORIGINS` | dev Vite origins | CORS list; **empty in single-origin kiosk** |
| `SS_LOG_LEVEL` | `INFO` | log verbosity |
| `SS_WARMUP` | `1` | load models at startup (readiness gate) |
| `SS_SESSION_TTL_SECONDS` | `1800` | idle session + data-dir reap age |
| `SS_MAX_SESSIONS` | `64` | in-memory session cap (LRU) |
| `SS_PERSIST_REPORTS` | `1` | write `report_v<n>.json` on seal |

## 3. Warmup & readiness

With `SS_WARMUP=1`, models load on a background thread at startup instead of on the
first patient (the ~80 s Kokoro cold load in particular). While warming:

- `GET /api/health` → `200` immediately (liveness).
- `GET /api/ready` → `{ ready, warming, loaded, unavailable, seconds }`.
- The UI shows a **"Warming up…"** chip and disables **Process** until `ready:true`.

Warmup respects the env's `max_resident_gpu_models` budget: CPU models (Kokoro,
Vaani STT) stay resident; GPU models are touched then released. It is **best-effort**
— if Ollama is down or a weight file is missing, that model is listed under
`unavailable` and the server still starts; the failure surfaces (cleanly) at stage
time.

## 4. Run

**Windows (dev box):** `start_kiosk.bat` → browse to <http://localhost:8000>.

**Linux / Jetson Orin (production):** install the systemd unit so it starts on boot
and restarts on crash:

```bash
# edit paths/user in the unit first
sudo cp deploy/swasthya-sathi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swasthya-sathi
journalctl -u swasthya-sathi -f      # logs
```

**Windows autostart at logon:** register the scheduled task (elevated PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\install_windows_startup.ps1
```

## 5. Data, privacy & durability

- **Sessions are in-memory** (no database). A browser refresh **reattaches** to the
  still-live session (the session id is kept in `sessionStorage`); a process restart
  starts fresh.
- **Idle cleanup:** sessions idle past `SS_SESSION_TTL_SECONDS` are dropped and their
  `_session_data/<id>/` directory (uploads, audio, report) is **deleted** — nothing
  lingers on the box. Orphan dirs from a prior crashed run are swept at startup.
- **Sealed report on disk:** with `SS_PERSIST_REPORTS=1`, each sealed report is written
  to `_session_data/<id>/report_v<n>.json` (content + SHA-256 + timestamp) as an audit
  artifact — until that session is reaped.

## 6. Dependencies on the box

- **Ollama** running (summary model).
- `models/weights/` present (OCR, image-tag, Kokoro, Vaani).
- Python deps from `requirements.txt`; Node only to *build* the UI (not at runtime).
