"""Swasthya Sathi — one-click appliance setup (non-technical users).

Detects GPU/CPU, creates a venv, installs the right wheels, pulls the Phi
model via Ollama, warms RapidOCR, writes config/env/local.yaml, and can start
the kiosk. No prompts. Idempotent — safe to re-run.

CLI:
    python deploy/appliance_setup.py              # console progress
    python deploy/appliance_setup.py --gui        # simple progress window
    python deploy/appliance_setup.py --start      # setup then launch kiosk
    python deploy/appliance_setup.py --verify-only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[str, float], None]  # message, fraction 0..1


def _repo_root() -> Path:
    if getattr(sys, "frozen", False):
        # Setup.exe / Start.exe live at the appliance root.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


REPO_ROOT = _repo_root()
RUNTIME_DIR = REPO_ROOT / "runtime"
STATE_PATH = RUNTIME_DIR / "setup_state.json"
LOG_PATH = REPO_ROOT / "logs" / "setup.log"
VENV_DIR = REPO_ROOT / ".venv"
LOCAL_ENV_PATH = REPO_ROOT / "config" / "env" / "local.yaml"
OLLAMA_MODEL = "phi3.5:3.8b"
REQUIRED_PIP = [
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "python-multipart>=0.0.9",
    "pydantic>=2.7",
    "PyYAML>=6.0",
    "numpy>=1.26,<2",
    "opencv-python-headless>=4.9,<5",
    "PyMuPDF>=1.24",
    "Pillow",
    "rapidocr>=3.0",
    "httpx",
    "huggingface_hub>=0.23",
]

# Local CTranslate2 folders expected by config/models.yaml
VAANI_DIR = REPO_ROOT / "models" / "weights" / "whisper-large-v3-vaani-hindi-ct2-int8"
VAANI_REPO = "bjollans/whisper-large-v3-vaani-hindi-ct2"  # CT2 of ARTPARK Vaani Hindi
MULTILINGUAL_DIR = REPO_ROOT / "models" / "weights" / "faster-whisper-large-v3"
MULTILINGUAL_REPO = "Systran/faster-whisper-large-v3"
PIPER_DIR = REPO_ROOT / "models" / "weights" / "piper"

# Offline Ollama installer shipped inside the release (used as a winget fallback).
BUNDLED_OLLAMA = REPO_ROOT / "deploy" / "bundle" / "OllamaSetup.exe"


log = logging.getLogger("swasthya.setup")


@dataclass
class DeviceInfo:
    has_cuda: bool
    gpu_name: str | None = None
    vram_mb: int = 0
    arch: str = "x86"


@dataclass
class SetupResult:
    ok: bool
    device: DeviceInfo
    messages: list[str] = field(default_factory=list)
    error: str | None = None


def _ensure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not log.handlers:
        log.setLevel(logging.INFO)
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    log.info("run: %s", " ".join(args))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        env=merged,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=check,
    )


def detect_device() -> DeviceInfo:
    """Prefer nvidia-smi; fall back to CPU. Never asks the user."""
    gpu_name = None
    vram_mb = 0
    has_cuda = False
    try:
        proc = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            line = proc.stdout.strip().splitlines()[0]
            # e.g. "NVIDIA GeForce RTX 4060 Laptop GPU, 8188"
            parts = [p.strip() for p in line.split(",")]
            if parts:
                gpu_name = parts[0]
                has_cuda = True
            if len(parts) > 1:
                try:
                    vram_mb = int(float(parts[1]))
                except ValueError:
                    vram_mb = 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log.info("nvidia-smi unavailable (%s) — using CPU", exc)

    arch = "arm" if (os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper().startswith("ARM") else "x86"
    return DeviceInfo(has_cuda=has_cuda, gpu_name=gpu_name, vram_mb=vram_mb, arch=arch)


def find_system_python() -> Path:
    """Locate a host Python 3.10+ (not the venv)."""
    candidates: list[Path] = []
    for cmd in ("py", "python", "python3"):
        which = shutil.which(cmd)
        if which:
            candidates.append(Path(which))
    # Common Windows install locations
    local = os.environ.get("LOCALAPPDATA", "")
    for rel in (
        r"Programs\Python\Python313\python.exe",
        r"Programs\Python\Python312\python.exe",
        r"Programs\Python\Python311\python.exe",
        r"Programs\Python\Python310\python.exe",
    ):
        p = Path(local) / rel
        if p.exists():
            candidates.append(p)

    seen: set[str] = set()
    for cand in candidates:
        key = str(cand.resolve()) if cand.exists() else str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            proc = _run([str(cand), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"], timeout=20)
            if proc.returncode != 0:
                continue
            ver = proc.stdout.strip()
            major, minor = (int(x) for x in ver.split(".")[:2])
            if (major, minor) >= (3, 10):
                # Prefer launcher that is NOT already a venv interpreter when creating venv
                return Path(cand)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
    raise RuntimeError(
        "Python 3.10 or newer was not found. Please install Python from "
        "https://www.python.org/downloads/ and run Setup again."
    )


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv(progress: ProgressFn) -> Path:
    py = venv_python()
    if py.exists():
        progress("Using existing app environment…", 0.12)
        return py
    progress("Creating app environment…", 0.08)
    host = find_system_python()
    proc = _run([str(host), "-m", "venv", str(VENV_DIR)], timeout=180)
    if proc.returncode != 0 or not py.exists():
        raise RuntimeError(
            "Could not create the app environment.\n"
            f"{proc.stderr or proc.stdout or 'venv failed'}"
        )
    return py


def _pip(py: Path, *args: str, timeout: int = 1800) -> None:
    proc = _run([str(py), "-m", "pip", *args], timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            "Could not install a required component.\n"
            f"{(proc.stderr or proc.stdout)[-2000:]}"
        )


def install_python_deps(py: Path, device: DeviceInfo, progress: ProgressFn) -> None:
    progress("Updating installer tools…", 0.18)
    _pip(py, "install", "--upgrade", "pip", "wheel", "setuptools", timeout=300)

    progress("Installing core components…", 0.28)
    _pip(py, "install", *REQUIRED_PIP, timeout=1200)

    # ONNX Runtime: keep a working install; try GPU only if nothing importable yet.
    progress("Installing document reader…", 0.40)
    ort_ok = _run([str(py), "-c", "import onnxruntime as o; print(o.__version__)"], timeout=60)
    if ort_ok.returncode == 0:
        log.info("onnxruntime already present: %s", ort_ok.stdout.strip())
    elif device.has_cuda:
        proc = _run(
            [str(py), "-m", "pip", "install", "onnxruntime-gpu>=1.17"],
            timeout=600,
        )
        if proc.returncode != 0:
            log.warning("onnxruntime-gpu failed; installing CPU onnxruntime")
            _pip(py, "install", "onnxruntime>=1.17", timeout=600)
    else:
        _pip(py, "install", "onnxruntime>=1.17", timeout=600)

    # Torch: optional for image_tag / some TTS paths. Soft-fail if it fails.
    progress("Installing optional AI libraries…", 0.48)
    torch_ok = _run([str(py), "-c", "import torch; print(torch.__version__)"], timeout=60)
    if torch_ok.returncode == 0:
        log.info("torch already present: %s", torch_ok.stdout.strip())
    else:
        try:
            if device.has_cuda:
                _pip(
                    py,
                    "install",
                    "torch",
                    "torchvision",
                    "torchaudio",
                    "--index-url",
                    "https://download.pytorch.org/whl/cu126",
                    timeout=2400,
                )
            else:
                _pip(py, "install", "torch", "torchvision", "torchaudio", timeout=2400)
        except RuntimeError as exc:
            log.warning("torch install skipped: %s", exc)

    # Voice stack — soft (stubs cover missing weights).
    progress("Installing voice components…", 0.55)
    for pkg in ("soundfile>=0.12", "faster-whisper>=1.0", "kokoro>=0.9.4", "piper-tts>=1.5"):
        try:
            _pip(py, "install", pkg, timeout=900)
        except RuntimeError as exc:
            log.warning("optional package %s skipped: %s", pkg, exc)


def find_ollama() -> str | None:
    which = shutil.which("ollama")
    if which:
        return which
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ):
        if cand.exists():
            return str(cand)
    return None


def ollama_tags_ok(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ensure_ollama(progress: ProgressFn) -> None:
    progress("Checking language model service…", 0.62)
    if ollama_tags_ok():
        return
    ollama = find_ollama()
    if not ollama and BUNDLED_OLLAMA.exists():
        # Prefer the bundled offline installer (per-user, no admin needed).
        progress("Installing language model service…", 0.63)
        proc = _run(
            [str(BUNDLED_OLLAMA), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            timeout=900,
        )
        log.info("bundled ollama installer rc=%s", proc.returncode)
        ollama = find_ollama()
    if not ollama:
        # Try winget quietly (admin may be needed; soft message if fails).
        winget = shutil.which("winget")
        if winget:
            progress("Installing language model service…", 0.63)
            proc = _run(
                [
                    winget,
                    "install",
                    "-e",
                    "--id",
                    "Ollama.Ollama",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                ],
                timeout=900,
            )
            log.info("winget ollama rc=%s", proc.returncode)
            ollama = find_ollama()
        if not ollama:
            raise RuntimeError(
                "Ollama is required and was not found.\n"
                "Install it from https://ollama.com/download then run Setup again."
            )

    # Start serve in background
    progress("Starting language model service…", 0.66)
    subprocess.Popen(
        [ollama, "serve"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    for _ in range(60):
        if ollama_tags_ok():
            return
        time.sleep(1)
    raise RuntimeError(
        "Ollama did not start in time.\n"
        "Open the Ollama app once, then run Setup again."
    )


def ensure_phi_model(progress: ProgressFn) -> None:
    progress("Downloading language model (first time may take a while)…", 0.70)
    ollama = find_ollama() or "ollama"
    # Skip if already present
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = {m.get("name") or m.get("model") for m in data.get("models") or []}
        if any(OLLAMA_MODEL in (n or "") for n in names):
            progress("Language model already present…", 0.78)
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("could not list ollama tags: %s", exc)

    proc = _run([ollama, "pull", OLLAMA_MODEL], timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(
            "Could not download the language model.\n"
            "Check your internet connection and try again.\n"
            f"{(proc.stderr or proc.stdout)[-1500:]}"
        )


def _download_file(url: str, dest: Path, timeout: int = 600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "SwasthyaSathi-Setup/1.0"})
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            log.info("download %s -> %s (try %d)", url, dest, attempt)
            with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
                shutil.copyfileobj(resp, out)
            tmp.replace(dest)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            log.warning("download attempt %d failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError(f"download failed after retries: {url}\n{last_exc}")


def _hf_token() -> str | None:
    """Optional Hugging Face token to lift anonymous rate limits / gated repos.

    Looked up from the environment or config/hf_token.txt. Never logged.
    """
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    tok_file = REPO_ROOT / "config" / "hf_token.txt"
    try:
        if tok_file.exists():
            t = tok_file.read_text(encoding="utf-8").strip()
            if t:
                return t
    except OSError:
        pass
    return None


def _hf_snapshot(repo_id: str, dest: Path, *, label: str) -> None:
    """Download a Hub repo into dest. Resumable + retried. Expects CT2 model.bin.

    The common first-run failure is Hugging Face throttling a token-less multi-GB
    pull (HTTP 429), or a mid-download network drop. snapshot_download resumes
    already-fetched files, so we retry with exponential backoff; a token (if set)
    lifts the anonymous rate limit.
    """
    marker = dest / "model.bin"
    if marker.exists() and marker.stat().st_size > 1_000_000:
        log.info("%s already present at %s", label, dest)
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download speech models. Re-run Setup."
        ) from exc
    dest.mkdir(parents=True, exist_ok=True)
    token = _hf_token()
    log.info("snapshot_download %s -> %s (token=%s)", repo_id, dest, "yes" if token else "no")

    attempts = 5
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(dest),
                token=token,
                max_workers=2,          # fewer parallel connections -> fewer 429s
            )
            if marker.exists() and marker.stat().st_size > 1_000_000:
                return
            last_exc = RuntimeError("model.bin missing/too small after download")
        except Exception as exc:  # noqa: BLE001 — includes HfHubHTTPError (429), network
            last_exc = exc
            log.warning("%s download attempt %d/%d failed: %s", label, attempt, attempts, exc)
        if attempt < attempts:
            backoff = min(60, 5 * (2 ** (attempt - 1)))  # 5,10,20,40s
            log.info("retrying %s in %ds…", label, backoff)
            time.sleep(backoff)

    raise RuntimeError(
        f"{label} download did not complete after {attempts} tries (model.bin missing under {dest}).\n"
        "This is usually Hugging Face rate-limiting a token-less download (HTTP 429),\n"
        "not an internet outage. To fix, do ONE of:\n"
        "  • Set an HF read token: put it in config\\hf_token.txt (or HF_TOKEN env), re-run Setup.\n"
        "  • Pre-copy the models\\weights folder from a working PC into this install.\n"
        f"Last error: {last_exc}"
    )


def ensure_model_assets(py: Path, progress: ProgressFn) -> None:
    """Fetch STT/TTS weights expected by config/models.yaml (first-run, online)."""
    # Ensure hub client is importable even on older venvs.
    hub_ok = _run([str(py), "-c", "import huggingface_hub; print('ok')"], timeout=60)
    if hub_ok.returncode != 0:
        _pip(py, "install", "huggingface_hub>=0.23", timeout=300)

    progress("Downloading Hindi speech model (Vaani)…", 0.84)
    try:
        _hf_snapshot(VAANI_REPO, VAANI_DIR, label="Vaani Hindi STT")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not download the Hindi speech model (Vaani).\n"
            "Check internet and try Setup again.\n"
            f"{exc}"
        ) from exc

    progress("Downloading multilingual speech model…", 0.86)
    try:
        _hf_snapshot(MULTILINGUAL_REPO, MULTILINGUAL_DIR, label="Multilingual STT")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not download the multilingual speech model.\n"
            "Check internet and try Setup again.\n"
            f"{exc}"
        ) from exc

    progress("Downloading English voice…", 0.88)
    onnx = PIPER_DIR / "en_US-lessac-medium.onnx"
    meta = PIPER_DIR / "en_US-lessac-medium.onnx.json"
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"
    try:
        if not onnx.exists() or onnx.stat().st_size < 1_000_000:
            _download_file(f"{base}/en_US-lessac-medium.onnx", onnx)
        if not meta.exists():
            _download_file(f"{base}/en_US-lessac-medium.onnx.json", meta)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not download the English voice (Piper).\n"
            "Check internet and try Setup again.\n"
            f"{exc}"
        ) from exc


def write_local_env(device: DeviceInfo, progress: ProgressFn) -> None:
    progress("Configuring for this computer…", 0.82)
    LOCAL_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if device.has_cuda and device.vram_mb > 0:
        # Leave ~700 MB headroom for the desktop compositor.
        ceiling = max(2048, device.vram_mb - 700)
        device_line = "cuda"
        precision = "fp16"
        max_res = 1 if ceiling < 12000 else 2
    elif device.has_cuda:
        ceiling = 7500
        device_line = "cuda"
        precision = "fp16"
        max_res = 1
    else:
        ceiling = 0
        device_line = "cpu"
        precision = "fp32"
        max_res = 0

    # First-run may still need hub fetches for voice weights; after setup the
    # kiosk can run offline. Keep internet_allowed true so warm downloads work;
    # operators can flip it later.
    text = (
        f"name: local\n"
        f"device: {device_line}\n"
        f"vram_ceiling_mb: {ceiling}\n"
        f"max_resident_gpu_models: {max_res}\n"
        f"default_precision: {precision}\n"
        f"internet_allowed: true\n"
        f"arch: {device.arch}\n"
        f"encrypt_at_rest: false\n"
        f"data_dir: ./_session_data\n"
    )
    LOCAL_ENV_PATH.write_text(text, encoding="utf-8")


def ensure_ui(progress: ProgressFn) -> None:
    """Clinic machines must ship a prebuilt frontend/dist (no Node required)."""
    dist = REPO_ROOT / "frontend" / "dist" / "index.html"
    if dist.exists():
        progress("App screens ready…", 0.58)
        return
    raise RuntimeError(
        "App screens are missing (frontend\\dist).\n"
        "This copy was not packaged correctly.\n"
        "On the build PC run:  powershell -File deploy\\build_release.ps1\n"
        "Then copy the full folder (including frontend\\dist) to this computer."
    )

def warm_models(py: Path, progress: ProgressFn) -> None:
    progress("Preparing document reader…", 0.90)
    script = r"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "0")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "0")
from rapidocr import RapidOCR
import numpy as np
eng = RapidOCR()
img = np.zeros((64, 256, 3), dtype=np.uint8)
img[:] = 255
try:
    eng(img)
except Exception:
    pass
print("rapidocr_ok")
"""
    proc = _run([str(py), "-c", script], timeout=300, env={"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0"})
    if proc.returncode != 0 or "rapidocr_ok" not in (proc.stdout or ""):
        raise RuntimeError(
            "Document reader failed to prepare.\n"
            f"{(proc.stderr or proc.stdout)[-1500:]}"
        )

    # Soft: touch Ollama chat once so first patient is faster.
    progress("Warming language model…", 0.93)
    body = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "stream": False,
            "options": {"num_predict": 8},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001
        log.warning("ollama warm skipped: %s", exc)


def write_state(device: DeviceInfo, ok: bool, error: str | None = None) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "version": 1,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device": {
            "has_cuda": device.has_cuda,
            "gpu_name": device.gpu_name,
            "vram_mb": device.vram_mb,
            "arch": device.arch,
        },
        "ollama_model": OLLAMA_MODEL,
        "error": error,
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def verify_ready(py: Path | None = None) -> list[str]:
    """Return list of problem strings; empty means ready."""
    problems: list[str] = []
    py = py or (venv_python() if venv_python().exists() else None)
    if py is None or not Path(py).exists():
        problems.append("App environment missing")
    else:
        proc = _run([str(py), "-c", "import rapidocr, fastapi, cv2, fitz; print('ok')"], timeout=60)
        if proc.returncode != 0:
            problems.append("Core Python packages missing")
    if not (REPO_ROOT / "frontend" / "dist" / "index.html").exists():
        problems.append("App screens missing (frontend/dist) — run deploy\\build_release.ps1 on the build PC")
    if not LOCAL_ENV_PATH.exists():
        problems.append("Device profile missing")
    if not (VAANI_DIR / "model.bin").exists():
        problems.append("Hindi speech model (Vaani) missing")
    if not (MULTILINGUAL_DIR / "model.bin").exists():
        problems.append("Multilingual speech model missing")
    if not (PIPER_DIR / "en_US-lessac-medium.onnx").exists():
        problems.append("English voice (Piper) missing")
    if not ollama_tags_ok():
        problems.append("Language model service not running")
    else:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            names = {m.get("name") or m.get("model") for m in data.get("models") or []}
            if not any(OLLAMA_MODEL in (n or "") for n in names):
                problems.append(f"Model {OLLAMA_MODEL} not downloaded")
        except Exception:
            problems.append("Could not verify language model")
    return problems


def run_setup(progress: ProgressFn | None = None, *, force: bool = False) -> SetupResult:
    _ensure_logging()
    progress = progress or (lambda msg, frac: log.info("[%d%%] %s", int(frac * 100), msg))
    messages: list[str] = []

    def note(msg: str, frac: float) -> None:
        messages.append(msg)
        progress(msg, frac)

    device = detect_device()
    note(
        (
            f"Detected GPU: {device.gpu_name} ({device.vram_mb} MB)"
            if device.has_cuda
            else "No GPU detected — using CPU mode"
        ),
        0.05,
    )

    state = load_state()
    if state and state.get("ok") and not force:
        problems = verify_ready()
        if not problems:
            note("Already set up — ready to start.", 1.0)
            return SetupResult(ok=True, device=device, messages=messages)
        log.info("setup marker present but verify failed: %s", problems)

    try:
        py = ensure_venv(note)
        install_python_deps(py, device, note)
        ensure_ui(note)
        ensure_ollama(note)
        ensure_phi_model(note)
        write_local_env(device, note)
        ensure_model_assets(py, note)
        warm_models(py, note)
        problems = verify_ready(py)
        if problems:
            raise RuntimeError("Setup finished with issues:\n- " + "\n- ".join(problems))
        write_state(device, ok=True)
        note("Setup complete.", 1.0)
        return SetupResult(ok=True, device=device, messages=messages)
    except Exception as exc:  # noqa: BLE001
        err = str(exc).strip() or type(exc).__name__
        log.exception("setup failed")
        write_state(device, ok=False, error=err)
        note("Setup could not finish.", 1.0)
        return SetupResult(ok=False, device=device, messages=messages, error=err)


def start_kiosk() -> int:
    """Launch uvicorn + open browser. Blocks on the server process."""
    _ensure_logging()
    py = venv_python()
    if not py.exists():
        print("App is not set up yet. Run Setup first.")
        return 1

    # Ensure Ollama is up
    if not ollama_tags_ok():
        ollama = find_ollama()
        if ollama:
            subprocess.Popen(
                [ollama, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            for _ in range(45):
                if ollama_tags_ok():
                    break
                time.sleep(1)

    env = os.environ.copy()
    env.setdefault("SS_ENV", "local")
    env.setdefault("SS_HOST", "127.0.0.1")
    env.setdefault("SS_PORT", "8000")
    env.setdefault("SS_WARMUP", "1")
    env.setdefault("SS_LOG_LEVEL", "INFO")
    # After first setup, prefer offline libs if weights cached; still allow if needed.
    env.setdefault("HF_HUB_OFFLINE", "0")
    env.setdefault("TRANSFORMERS_OFFLINE", "0")

    port = env["SS_PORT"]
    url = f"http://127.0.0.1:{port}"

    chrome = None
    for cand in (
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ):
        if cand.exists():
            chrome = cand
            break

    def _open_when_ready() -> None:
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=2) as resp:
                    if 200 <= resp.status < 300:
                        break
            except Exception:
                time.sleep(1)
                continue
        else:
            return
        if chrome:
            subprocess.Popen(
                [
                    str(chrome),
                    f"--app={url}",
                    f"--user-data-dir={os.environ.get('TEMP', '.')}/ss_kiosk_chrome",
                    "--start-maximized",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        elif os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]

    threading.Thread(target=_open_when_ready, daemon=True).start()
    print(f"Starting Swasthya Sathi at {url}")
    print("You can close this window to stop the app.")
    proc = subprocess.run(
        [
            str(py),
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            env["SS_HOST"],
            "--port",
            port,
        ],
        cwd=str(REPO_ROOT),
        env=env,
    )
    return int(proc.returncode or 0)


def run_gui(*, start_after: bool = True) -> int:
    """Minimal Tk progress UI — no choices, plain language."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Swasthya Sathi")
    root.geometry("480x220")
    root.resizable(False, False)

    title = tk.Label(root, text="Swasthya Sathi", font=("Segoe UI", 16, "bold"))
    title.pack(pady=(18, 4))
    subtitle = tk.Label(root, text="Preparing your computer…", font=("Segoe UI", 10))
    subtitle.pack()
    bar = ttk.Progressbar(root, mode="determinate", length=400, maximum=100)
    bar.pack(pady=18)
    status = tk.Label(root, text="", font=("Segoe UI", 9), wraplength=420, justify="center")
    status.pack(padx=16)
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)
    result_box: dict = {"result": None}

    def set_progress(msg: str, frac: float) -> None:
        def _apply() -> None:
            status.config(text=msg)
            bar["value"] = max(0, min(100, int(frac * 100)))

        root.after(0, _apply)

    def worker() -> None:
        result_box["result"] = run_setup(set_progress)

        def _done() -> None:
            res: SetupResult = result_box["result"]
            if res.ok:
                subtitle.config(text="Ready")
                status.config(text="Setup complete. Starting the app…")
                if start_after:
                    root.after(600, lambda: (root.destroy(), None))
                else:
                    ttk.Button(btn_frame, text="Close", command=root.destroy).pack()
            else:
                subtitle.config(text="Something went wrong")
                status.config(
                    text=(res.error or "Setup could not finish. Check your internet and try again.")
                    + f"\n\nDetails saved to: {LOG_PATH}"
                )
                ttk.Button(btn_frame, text="Close", command=root.destroy).pack()

        root.after(0, _done)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    res = result_box.get("result")
    if not res or not res.ok:
        return 1
    if start_after:
        return start_kiosk()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Swasthya Sathi appliance setup")
    ap.add_argument("--gui", action="store_true", help="Show simple progress window")
    ap.add_argument("--start", action="store_true", help="Start the app after setup")
    ap.add_argument("--start-only", action="store_true", help="Skip setup; just start")
    ap.add_argument("--force", action="store_true", help="Re-run setup even if marked done")
    ap.add_argument("--verify-only", action="store_true", help="Check readiness and exit")
    args = ap.parse_args(argv)
    _ensure_logging()

    if args.verify_only:
        problems = verify_ready()
        if problems:
            print("NOT READY:")
            for p in problems:
                print(" -", p)
            return 1
        print("READY")
        return 0

    if args.start_only:
        return start_kiosk()

    if args.gui:
        # GUI path always continues into the app after a successful setup —
        # non-technical users should not have a second step.
        return run_gui(start_after=True)

    def progress(msg: str, frac: float) -> None:
        print(f"[{int(frac * 100):3d}%] {msg}", flush=True)

    result = run_setup(progress, force=args.force)
    if not result.ok:
        print("\nSetup failed:")
        print(result.error or "Unknown error")
        print(f"Log: {LOG_PATH}")
        return 1
    if args.start:
        return start_kiosk()
    print("\nSetup OK. Double-click SwasthyaSathi.bat (or run with --start) to open the app.")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    # Setup.exe (frozen) with no args → full GUI setup + start.
    if getattr(sys, "frozen", False) and not argv:
        argv = ["--gui", "--start"]
    raise SystemExit(main(argv))
