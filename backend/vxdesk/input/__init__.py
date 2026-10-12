"""Input layer: mouse / keyboard / window control with a global dry-run safety flag.

When dry-run is active (``VXDESK_DRY_RUN=1`` env var, :func:`set_dry_run`, or a
per-call ``dry_run=True``) every action is logged instead of executed, so a full
workflow can be rehearsed without touching the real desktop.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Optional, Sequence, Union

logger = logging.getLogger("vxdesk.input")

try:  # pyautogui needs a display session; probe instead of crashing headless.
    import pyautogui

    pyautogui.FAILSAFE = True  # slam mouse to a corner to abort
    pyautogui.PAUSE = 0.02
    _PYAUTOGUI_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - headless machines only
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_ERROR = str(exc)
    logger.warning("pyautogui unavailable: %s", exc)

_dry_run: bool = os.environ.get("VXDESK_DRY_RUN", "").strip() in {"1", "true", "yes"}


def set_dry_run(flag: bool) -> None:
    global _dry_run
    _dry_run = bool(flag)


def is_dry_run() -> bool:
    return _dry_run


def _active(dry_run: Optional[bool], action: str, **detail) -> bool:
    """Return True when the action must really happen; log when suppressed."""
    if dry_run is None:
        dry_run = _dry_run
    if dry_run:
        logger.info("DRY-RUN %s %s", action, detail)
        return False
    if pyautogui is None:
        raise RuntimeError(f"input backend unavailable: {_PYAUTOGUI_ERROR}")
    logger.debug("%s %s", action, detail)
    return True


def click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    dry_run: Optional[bool] = None,
) -> dict:
    x, y = int(x), int(y)
    clicks = max(1, int(clicks))
    if _active(dry_run, "click", x=x, y=y, button=button, clicks=clicks):
        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    return {"x": x, "y": y}


def move(x: int, y: int, duration_ms: int = 0, dry_run: Optional[bool] = None) -> dict:
    x, y = int(x), int(y)
    if _active(dry_run, "move", x=x, y=y):
        pyautogui.moveTo(x, y, duration=max(0, duration_ms) / 1000.0)
    return {"x": x, "y": y}


def drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    button: str = "left",
    dry_run: Optional[bool] = None,
) -> dict:
    if _active(dry_run, "drag", from_=(x1, y1), to=(x2, y2)):
        pyautogui.moveTo(int(x1), int(y1))
        pyautogui.dragTo(int(x2), int(y2), duration=max(0, duration_ms) / 1000.0, button=button)
    return {}


def type_text(text: str, interval_ms: int = 0, dry_run: Optional[bool] = None) -> dict:
    if _active(dry_run, "type_text", length=len(text)):
        pyautogui.typewrite(text, interval=max(0, interval_ms) / 1000.0)
    return {}


def press_key(keys: Union[str, Sequence[str]], dry_run: Optional[bool] = None) -> dict:
    """Press a single key (``"enter"``) or a chord (``["ctrl", "s"]``)."""
    if isinstance(keys, str):
        keys = [keys]
    keys = [str(k).lower() for k in keys]
    if not keys:
        return {}
    if _active(dry_run, "press_key", keys=keys):
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
    return {}


def list_windows() -> list[dict]:
    """All top-level windows with title and absolute rect."""
    import pygetwindow as gw  # noqa: PLC0415

    out = []
    for win in gw.getAllWindows():
        try:
            title = win.title or ""
            if not title.strip():
                continue
            hwnd = int(win._hWnd)  # pygetwindow exposes no public hwnd accessor
            out.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "rect": {
                        "x": int(win.left),
                        "y": int(win.top),
                        "w": int(win.width),
                        "h": int(win.height),
                    },
                    "visible": bool(win.visible),
                }
            )
        except Exception as exc:
            logger.debug("skipping window: %s", exc)
    return out


def focus_window(title: str, dry_run: Optional[bool] = None) -> dict:
    """Focus the first window whose title contains ``title`` (case-insensitive)."""
    needle = title.lower()
    for win in list_windows():
        if needle in win["title"].lower():
            if _active(dry_run, "focus_window", title=win["title"]):
                _bring_to_front(win["hwnd"])
            return {"found": True, "rect": win["rect"], "title": win["title"], "hwnd": win["hwnd"]}
    return {"found": False, "rect": None, "title": None, "hwnd": None}


def _bring_to_front(hwnd: int) -> None:
    import win32con  # noqa: PLC0415
    import win32gui  # noqa: PLC0415

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        # SetForegroundWindow is often blocked by foreground-lock rules; the
        # window is still raised via ShowWindow, so degrade to a warning.
        logger.warning("SetForegroundWindow(%s) failed: %s", hwnd, exc)


def launch(command: str, wait_ms: int = 0, dry_run: Optional[bool] = None) -> dict:
    """Launch a process via the shell; returns ``{"pid": ...}`` when started."""
    if _active(dry_run, "launch", command=command):
        proc = subprocess.Popen(command, shell=True)  # noqa: S602 - user-authored command
        if wait_ms:
            time.sleep(max(0, wait_ms) / 1000.0)
        return {"pid": proc.pid}
    if wait_ms:
        time.sleep(max(0, wait_ms) / 1000.0)
    return {"pid": None}
