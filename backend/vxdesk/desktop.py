"""Desktop entry point: uvicorn in a daemon thread + native WebView2 window.

Usage:
    python -m vxdesk.desktop              # native window (browser fallback)
    python -m vxdesk.desktop --browser    # open in the default browser
    python -m vxdesk.desktop --server-only  # headless: just the API server

Startup is window-first: the native window appears immediately with a loading
screen, the backend spins up behind it, and the window navigates once the API
is ready — so a double-click always gives instant visual feedback. Everything
is also written to ``logs/desktop.log`` under the data dir, since a windowed
exe has no console for errors. The window closing (or Ctrl+C in server-only
mode) shuts uvicorn down and exits 0.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser

logger = logging.getLogger("vxdesk.desktop")

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

LOADING_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:#EFEDE6;display:flex;align-items:center;justify-content:center;
    font-family:'Manrope',system-ui,'Segoe UI',sans-serif}
  .card{text-align:center}
  .logo{font-family:'Cal Sans','Segoe UI',sans-serif;font-size:44px;font-weight:600;color:#2A2A2A;letter-spacing:-0.02em}
  .dot{display:inline-block;width:14px;height:14px;border-radius:50%;background:#FF6B4A;margin-right:10px}
  .msg{margin-top:10px;color:#54453F;font-size:14px}
  .bar{width:220px;height:6px;border-radius:999px;background:#E5E0D5;margin:18px auto 0;overflow:hidden}
  .fill{height:100%;width:40%;border-radius:999px;background:#FFB583;animation:slide 1.1s ease-in-out infinite}
  @keyframes slide{0%{margin-left:-40%}100%{margin-left:100%}}
</style></head>
<body><div class="card">
  <div class="logo"><span class="dot"></span>VxDesk</div>
  <div class="msg">Warming up your automation engine…</div>
  <div class="bar"><div class="fill"></div></div>
</div></body></html>"""


def _error_html(detail: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{{margin:0;height:100%;background:#EFEDE6;display:flex;align-items:center;justify-content:center;
    font-family:system-ui,'Segoe UI',sans-serif}}
  .card{{max-width:420px;text-align:center;color:#2A2A2A}}
  h1{{font-size:22px}} p{{color:#54453F;font-size:13.5px;line-height:1.6}}
</style></head>
<body><div class="card">
  <h1>VxDesk couldn't start</h1>
  <p>{detail}</p>
  <p>Check the log at <b>%LOCALAPPDATA%\\VxDesk\\logs\\desktop.log</b> and try again.
     If it keeps happening, reinstall the app.</p>
</div></body></html>"""


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, port)) != 0


def pick_port() -> int:
    if _port_free(DEFAULT_PORT):
        return DEFAULT_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _add_file_logging() -> None:
    """Windowed exes have no console — always log to a file as well."""
    try:
        from vxdesk.paths import ROOT  # absolute import: PyInstaller entry quirk

        logdir = ROOT / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(logdir / "desktop.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
    except Exception:  # never let logging setup break startup
        pass


def _bring_to_front(title: str = "VxDesk") -> None:
    """Best-effort: restore and foreground the app window (Windows)."""
    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        found: list[int] = []

        def _cb(hwnd: int, _: object) -> None:
            if win32gui.IsWindowVisible(hwnd) and title in win32gui.GetWindowText(hwnd):
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if not found:
            return
        hwnd = found[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        time.sleep(0.2)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass  # foreground rights are best-effort from a background thread
    except Exception:
        pass


class ServerThread(threading.Thread):
    """uvicorn running programmatically in a daemon thread."""

    def __init__(self, port: int) -> None:
        super().__init__(name="vxdesk-server", daemon=True)
        self.port = port
        self._server = None

    def run(self) -> None:
        import uvicorn

        # absolute import: PyInstaller runs this file as a top-level script
        from vxdesk.server import create_app

        config = uvicorn.Config(
            create_app(), host=HOST, port=self.port, log_level="warning",
            loop="asyncio",
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        import httpx

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = httpx.get(f"http://{HOST}:{self.port}/api/system/info",
                                 timeout=2.0)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def _serve_blocking(server: ServerThread, url: str) -> int:
    """Server-only / browser mode: run until Ctrl+C."""
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vxdesk", description="VxDesk desktop app")
    parser.add_argument("--browser", action="store_true",
                        help="open in the default browser instead of a native window")
    parser.add_argument("--server-only", action="store_true",
                        help="run only the API server (no window)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _add_file_logging()

    port = pick_port()
    if port != DEFAULT_PORT:
        logger.warning("port %d is busy — using ephemeral port %d", DEFAULT_PORT, port)
    url = f"http://{HOST}:{port}/"

    if args.server_only:
        server = ServerThread(port)
        server.start()
        if not server.wait_ready():
            logger.error("backend did not become ready on %s", url)
            server.shutdown()
            return 1
        print(f"VxDesk server running at {url} (Ctrl+C to stop)")
        return _serve_blocking(server, url)

    if args.browser:
        server = ServerThread(port)
        server.start()
        if not server.wait_ready():
            logger.error("backend did not become ready on %s", url)
            server.shutdown()
            return 1
        webbrowser.open(url)
        return _serve_blocking(server, url)

    try:
        import webview
    except Exception as exc:
        logger.warning("pywebview unavailable: %s — browser mode", exc)
        server = ServerThread(port)
        server.start()
        if server.wait_ready():
            webbrowser.open(url)
        return _serve_blocking(server, url)

    # Window-first startup: show the loading screen immediately, then swap in
    # the real UI once the backend answers.
    server = ServerThread(port)
    server.start()
    window = webview.create_window("VxDesk", html=LOADING_HTML,
                                   width=1280, height=800, min_size=(960, 600))

    def _watch() -> None:
        if server.wait_ready():
            logger.info("backend ready at %s — loading UI", url)
            try:
                window.load_url(url)
                time.sleep(1.0)
                _bring_to_front()
            except Exception as exc:
                logger.warning("load_url failed: %s", exc)
        else:
            logger.error("backend did not become ready on %s", url)
            try:
                window.load_html(_error_html(
                    "The automation engine did not start within 30 seconds."))
            except Exception:
                pass

    threading.Thread(target=_watch, name="vxdesk-watch", daemon=True).start()

    try:
        webview.start()  # blocks until the window closes
    except Exception as exc:
        logger.warning("native window failed (%s) — browser mode", exc)
        if server.wait_ready():
            webbrowser.open(url)
        return _serve_blocking(server, url)
    server.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
