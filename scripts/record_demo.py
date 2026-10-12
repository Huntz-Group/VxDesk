"""Record the README demo GIF (docs/demo.gif).

Starts from a running dev stack (npm run dev), opens the editor on a paced
demo workflow, triggers a real run through the REST API, and captures the
browser window while nodes light up and the console streams. Frames are
assembled into docs/demo.gif.

Usage:
    1. npm run dev                       # in another terminal
    2. backend/.venv/Scripts/python.exe scripts/record_demo.py

The demo workflow file is temporary and removed afterwards.
"""
import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import time
import urllib.request

import mss
import pyautogui
import pygetwindow as gw
from PIL import Image

pyautogui.FAILSAFE = True

# Never route localhost through a corporate proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_GIF = os.path.join(ROOT, "docs", "demo.gif")
DEMO_WF_PATH = os.path.join(ROOT, "workflows", "wf_demo_recording.json")
BACKEND = "http://127.0.0.1:8765"
FRONTEND = "http://localhost:7100"

FRAME_DT = 0.16       # seconds between frames (~6 fps)
MAX_DURATION = 22.0   # hard cap on capture length
RUN_AT = 3.0          # seconds into capture when the run is triggered
TAIL_AFTER_DONE = 3.0 # keep recording this long after the run completes
GIF_WIDTH = 1000      # output width in px
BROWSER_HINTS = ("chrome", "msedge", "firefox", "brave", "opera", "arc")

DEMO_WORKFLOW = {
    "id": "wf_demo_recording",
    "name": "Demo · VxDesk tour (recording)",
    "description": "Paced tour used to record the README GIF. Safe: no mouse/keyboard input.",
    "variables": {"user": "VxDesk demo"},
    "nodes": [
        {"id": "n1", "type": "trigger.manual", "name": "Start",
         "position": {"x": 0, "y": 110}, "params": {}},
        {"id": "n2", "type": "control.set_variable", "name": "Set user",
         "position": {"x": 210, "y": 110}, "params": {"name": "user", "value": "VxDesk demo"}},
        {"id": "w1", "type": "control.wait", "name": "Wait",
         "position": {"x": 420, "y": 110}, "params": {"ms": 1200}},
        {"id": "n3", "type": "control.log", "name": "Say hello",
         "position": {"x": 620, "y": 110},
         "params": {"message": "Hello {{ vars.user }}! The VxDesk engine is alive."}},
        {"id": "w2", "type": "control.wait", "name": "Wait",
         "position": {"x": 830, "y": 110}, "params": {"ms": 1200}},
        {"id": "n4", "type": "control.condition", "name": "Name long enough?",
         "position": {"x": 1030, "y": 110}, "params": {"expression": "len('{{ vars.user }}') > 3"}},
        {"id": "w3", "type": "control.wait", "name": "Wait",
         "position": {"x": 1270, "y": 25}, "params": {"ms": 1200}},
        {"id": "n5", "type": "output.save_screenshot", "name": "Save screenshot",
         "position": {"x": 1470, "y": 20}, "params": {"path": "runs/demo_shot.png"}},
        {"id": "n6", "type": "control.log", "name": "Log success",
         "position": {"x": 1700, "y": 25},
         "params": {"message": "Condition passed — screenshot saved ({{ n5.output.path }})."}},
        {"id": "n7", "type": "control.log", "name": "Log failure",
         "position": {"x": 1280, "y": 210},
         "params": {"message": "Condition failed — this should not happen."}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"},
        {"id": "e2", "source": "n2", "target": "w1", "sourceHandle": "default"},
        {"id": "e3", "source": "w1", "target": "n3", "sourceHandle": "default"},
        {"id": "e4", "source": "n3", "target": "w2", "sourceHandle": "default"},
        {"id": "e5", "source": "w2", "target": "n4", "sourceHandle": "default"},
        {"id": "e6", "source": "n4", "target": "w3", "sourceHandle": "true"},
        {"id": "e7", "source": "w3", "target": "n5", "sourceHandle": "default"},
        {"id": "e8", "source": "n5", "target": "n6", "sourceHandle": "default"},
        {"id": "e9", "source": "n4", "target": "n7", "sourceHandle": "false"},
    ],
}


def wait_http(url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _OPENER.open(url, timeout=3) as r:
                if r.status < 500:
                    return
        except Exception:
            pass
        time.sleep(1.0)
    raise TimeoutError(f"server not ready: {url}")


def process_name(hwnd: int) -> str:
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = ctypes.wintypes.DWORD(512)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def vxdesk_windows() -> list:
    wins = []
    for w in gw.getAllWindows():
        try:
            if "vxdesk" in w.title.lower() and w.width > 200 and w.height > 200:
                wins.append(w)
        except Exception:
            continue
    return wins


def open_browser() -> object:
    before = {w._hWnd for w in vxdesk_windows()}
    subprocess.Popen(["explorer.exe", f"{FRONTEND}/workflow/wf_demo_recording"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline:
        for w in vxdesk_windows():
            if w._hWnd not in before and any(h in process_name(w._hWnd) for h in BROWSER_HINTS):
                return w
        time.sleep(0.5)
    # Fallback: reuse an existing browser window already showing VxDesk
    for w in vxdesk_windows():
        if any(h in process_name(w._hWnd) for h in BROWSER_HINTS):
            return w
    wins = vxdesk_windows()
    if wins:
        return wins[0]
    raise RuntimeError("could not find the browser window showing VxDesk")


def trigger_run(win) -> None:
    """Click the editor's Run button so the UI attaches to the live run.

    Coordinates are the Run button's position relative to the (maximized)
    browser window — measured from a captured frame of the editor layout.
    """
    x = win.left + int(0.024 * win.width)
    y = win.top + int(0.797 * win.height)
    pyautogui.click(x, y)
    print(f"  Run clicked at ({x}, {y})")


def _logical_monitors() -> list:
    """Logical rects of all monitors, same EnumDisplayMonitors order as mss."""
    from ctypes import wintypes
    rects = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, hdc, lprc, dwdata):
        r = lprc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return rects


def window_physical_rect(sct, win):
    """Map the window's logical rect onto physical pixels of its monitor.

    Returns (mss_monitor, (x0, y0, x1, y0crop...)) — per-monitor DPI aware.
    """
    logs = _logical_monitors()
    cx, cy = win.left + win.width // 2, win.top + win.height // 2
    idx = 0
    for i, (l, t, r, b) in enumerate(logs):
        if l <= cx < r and t <= cy < b:
            idx = i
            break
    idx = min(idx, len(sct.monitors[1:]) - 1)
    m = sct.monitors[1 + idx]
    l, t, r, b = logs[idx] if idx < len(logs) else (
        m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])
    sx = m["width"] / max(1, r - l)
    sy = m["height"] / max(1, b - t)
    x0 = m["left"] + int((win.left - l) * sx)
    y0 = m["top"] + int((win.top - t) * sy)
    x1 = m["left"] + int((win.left + win.width - l) * sx)
    y1 = m["top"] + int((win.top + win.height - t) * sy)
    x0, y0 = max(x0, m["left"]), max(y0, m["top"])
    x1, y1 = min(x1, m["left"] + m["width"]), min(y1, m["top"] + m["height"])
    if x1 - x0 < 100 or y1 - y0 < 100:  # defensive: fall back to whole monitor
        return m, (m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])
    return m, (x0, y0, x1, y1)


def latest_run_status() -> str:
    """Status of the most recent run of the demo workflow ('' if unknown)."""
    try:
        with _OPENER.open(f"{BACKEND}/api/workflows/wf_demo_recording/runs", timeout=3) as r:
            runs = json.loads(r.read())
        if runs:
            return str(runs[0].get("status", ""))
    except Exception:
        pass
    return ""


def dpi_scale() -> float:
    logical_w = ctypes.windll.user32.GetSystemMetrics(0)
    with mss.mss() as sct:
        phys_w = sct.monitors[1]["width"]
    return phys_w / logical_w if logical_w else 1.0


def main() -> None:
    print("1/5 waiting for dev servers…")
    wait_http(f"{BACKEND}/api/system/info")
    wait_http(FRONTEND)

    print("2/5 installing demo workflow…")
    with open(DEMO_WF_PATH, "w", encoding="utf-8") as f:
        json.dump(DEMO_WORKFLOW, f, indent=2)

    try:
        print("3/5 opening browser…")
        win = open_browser()
        # Move to the primary monitor so logical→physical scaling is uniform.
        try:
            if win.isMaximized:
                win.restore()
                time.sleep(0.6)
        except Exception:
            pass
        try:
            win.moveTo(80, 60)
            time.sleep(0.8)
            win.activate()
            time.sleep(0.4)
            win.maximize()
        except Exception as e:
            print("  window move/maximize warning:", e)
        time.sleep(1.2)
        print("  window:", win.title[:60], win.left, win.top, win.width, win.height)
        time.sleep(5)  # let the editor fetch the workflow and settle

        scale = dpi_scale()
        print(f"  dpi_scale(primary)={scale:.2f}")

        print(f"4/5 capturing (run fires at {RUN_AT:.0f}s, stops {TAIL_AFTER_DONE:.0f}s after done)…")
        frames = []
        t0 = time.perf_counter()
        run_fired = False
        done_at = None
        with mss.mss() as sct:
            mon, rect = window_physical_rect(sct, win)
            print(f"  monitor={mon} rect={rect}")
            while True:
                t = time.perf_counter() - t0
                if t >= MAX_DURATION:
                    print("  hit max duration")
                    break
                if not run_fired and t >= RUN_AT:
                    trigger_run(win)
                    run_fired = True
                if run_fired and done_at is None and t > RUN_AT + 2:
                    status = latest_run_status()
                    if status in ("success", "failed", "stopped"):
                        print(f"  run finished with status={status} at {t:.1f}s")
                        done_at = t
                if done_at is not None and t >= done_at + TAIL_AFTER_DONE:
                    break
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                img = img.crop((rect[0] - mon["left"], rect[1] - mon["top"],
                                rect[2] - mon["left"], rect[3] - mon["top"]))
                h = int(img.height * GIF_WIDTH / img.width)
                frames.append(img.resize((GIF_WIDTH, h), Image.LANCZOS))
                time.sleep(max(0, FRAME_DT - (time.perf_counter() - t0 - t)))

        print(f"5/5 assembling GIF ({len(frames)} frames)…")
        frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                       duration=int(FRAME_DT * 1000), loop=0, optimize=True)
        size_mb = os.path.getsize(OUT_GIF) / 1e6
        print(f"  wrote {OUT_GIF} ({size_mb:.1f} MB)")
        if size_mb > 12:
            print("  WARNING: GIF is large; consider lowering GIF_WIDTH or FRAME_DT")
    finally:
        if os.path.exists(DEMO_WF_PATH):
            os.remove(DEMO_WF_PATH)
            print("  demo workflow removed")


if __name__ == "__main__":
    main()
