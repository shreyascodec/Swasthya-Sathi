"""Thin Setup.exe entry — no ML stacks bundled.

Runs deploy/appliance_setup.py --gui --start with the project venv when
present, otherwise with the host Python (which creates the venv on first run).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _find_host_python() -> str:
    import shutil

    for cmd in ("py", "python", "python3"):
        which = shutil.which(cmd)
        if not which:
            continue
        try:
            out = subprocess.check_output(
                [which, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                text=True,
                timeout=20,
            ).strip()
            major, minor = (int(x) for x in out.split(".")[:2])
            if (major, minor) >= (3, 10):
                return which
        except Exception:
            continue
    raise SystemExit(
        "Python 3.10+ was not found.\n"
        "Install it from https://www.python.org/downloads/ then run Setup again."
    )


def main() -> int:
    root = _root()
    os.chdir(root)
    script = root / "deploy" / "appliance_setup.py"
    if not script.exists():
        raise SystemExit(
            f"Missing {script}.\nKeep Setup.exe inside the Swasthya Sathi folder."
        )

    venv_py = root / ".venv" / "Scripts" / "python.exe"
    runner = str(venv_py) if venv_py.exists() else _find_host_python()
    return subprocess.call(
        [runner, str(script), "--gui", "--start"],
        cwd=str(root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
