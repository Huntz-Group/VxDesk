"""Build the VxDesk desktop app and (optionally) the Inno Setup installer.

Usage (from the repo root):
    backend/.venv/Scripts/python.exe scripts/build_desktop.py [--skip-frontend] [--skip-installer]

Steps:
1. npm.cmd --prefix frontend run build   (unless --skip-frontend)
2. PyInstaller packaging/vxdesk.spec -> dist/VxDesk/   (clean each time)
3. tools/innosetup/ISCC.exe packaging/vxdesk.iss -> installer-output/   (unless --skip-installer)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENV_PY = REPO / "backend" / ".venv" / "Scripts" / "python.exe"
SPEC = REPO / "packaging" / "vxdesk.spec"
ISS = REPO / "packaging" / "vxdesk.iss"
ISCC = REPO / "tools" / "innosetup" / "ISCC.exe"
DIST = REPO / "dist"
WORK = REPO / "build" / "pyinstaller"
INSTALLER_OUT = REPO / "installer-output"


def run(cmd: list[str], **kwargs) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    started = time.time()
    subprocess.run([str(c) for c in cmd], cwd=REPO, check=True, **kwargs)
    print(f"  ({time.time() - started:.0f}s)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()

    if not args.skip_frontend:
        run(["npm.cmd", "--prefix", "frontend", "run", "build"], shell=False)

    if not (REPO / "frontend" / "dist" / "index.html").is_file():
        print("ERROR: frontend/dist/index.html missing — build the frontend first")
        return 1

    run([
        VENV_PY, "-m", "PyInstaller", str(SPEC),
        "--distpath", str(DIST), "--workpath", str(WORK),
        "--clean", "-y", "--log-level", "WARN",
    ])

    exe = DIST / "VxDesk" / "VxDesk.exe"
    if not exe.is_file():
        print("ERROR: expected output missing:", exe)
        return 1
    print(f"OK: {exe}")

    if not args.skip_installer:
        if not ISCC.is_file():
            print("ERROR: Inno Setup not found at", ISCC)
            return 1
        run([ISCC, "/Q", str(ISS)])
        print("OK: installer in", INSTALLER_OUT)

    return 0


if __name__ == "__main__":
    sys.exit(main())
