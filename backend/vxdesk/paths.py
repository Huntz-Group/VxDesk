"""Filesystem locations for runtime data (workflows, runs, template assets).

In dev, runtime data lives at the repo root. When running frozen (PyInstaller,
``sys.frozen``), user data moves to ``%LOCALAPPDATA%\\VxDesk`` so the install
directory stays read-only-ish and uninstalls never touch user data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _data_root() -> Path:
    # Explicit override wins — used by the MCP/plugin entry point so it can
    # share data with an installed (frozen) copy of the app.
    override = os.environ.get("VXDESK_DATA_DIR")
    if override:
        return Path(override)
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "VxDesk"
        return Path.home() / "AppData" / "Local" / "VxDesk"
    # backend/vxdesk/paths.py -> repo root is two levels up from the package dir.
    return Path(__file__).resolve().parents[2]


ROOT: Path = _data_root()
WORKFLOWS_DIR: Path = ROOT / "workflows"
RUNS_DIR: Path = WORKFLOWS_DIR / ".runs"
TEMPLATES_DIR: Path = ROOT / "assets" / "templates"
SCREENSHOTS_DIR: Path = ROOT / "runs"
SETTINGS_FILE_PATH: Path = ROOT / "ai-settings.json"


def bundle_dir() -> Path:
    """Directory holding read-only bundled resources (frontend, samples)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def ensure_dirs() -> None:
    """Create runtime directories if they do not exist yet."""
    for d in (WORKFLOWS_DIR, RUNS_DIR, TEMPLATES_DIR, SCREENSHOTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
