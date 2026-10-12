"""Recording session manager wrapping pynput mouse/keyboard listeners.

pynput is imported lazily and guarded, so tests and headless contexts never
hard-fail — tests monkeypatch the module-level ``_MOUSE`` / ``_KEYBOARD``
namespaces with fake listener classes. Listeners are always cleaned up on
stop / discard / convert and via ``atexit``.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
import uuid
from typing import Callable, Optional

import numpy as np

from ..capture import Capture

logger = logging.getLogger("vxdesk.recorder.capture")

CROP_SIZE = 80  # ~80x80 smart-mode template crop around each click

_MOUSE = None
_KEYBOARD = None
_PYNPUT_ERROR: Optional[str] = None


def _pynput():
    """Lazily import pynput; returns (mouse, keyboard) or (None, None)."""
    global _MOUSE, _KEYBOARD, _PYNPUT_ERROR
    if _MOUSE is None and _PYNPUT_ERROR is None:
        try:
            from pynput import keyboard as kb
            from pynput import mouse as ms

            _MOUSE, _KEYBOARD = ms, kb
        except Exception as exc:  # pragma: no cover - platform dependent
            _PYNPUT_ERROR = str(exc)
            logger.warning("pynput unavailable: %s", exc)
    return _MOUSE, _KEYBOARD


def _foreground_title() -> str:
    """Best-effort foreground window title via pywin32."""
    try:
        import win32gui  # noqa: PLC0415

        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


_KEY_NAMES = {
    "enter": "enter", "tab": "tab", "esc": "esc", "backspace": "backspace",
    "delete": "delete", "space": "space", "up": "up", "down": "down",
    "left": "left", "right": "right", "home": "home", "end": "end",
    "page_up": "pageup", "page_down": "pagedown", "insert": "insert",
    "caps_lock": "capslock", "num_lock": "numlock", "scroll_lock": "scrolllock",
    "print_screen": "printscreen", "pause": "pause", "menu": "menu",
}

_MODIFIER_NAMES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
}
MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")


def _classify_key(key) -> tuple[str, str]:
    """Map a pynput key to (category, name): char | key | modifier."""
    char = getattr(key, "char", None)
    if char is not None:
        if char.isprintable():
            return ("char", char)
        return ("key", f"key_{ord(char)}")
    name = getattr(key, "name", None) or str(key).rsplit(".", 1)[-1].lower()
    if name in _MODIFIER_NAMES:
        return ("modifier", _MODIFIER_NAMES[name])
    if name in _KEY_NAMES:
        return ("key", _KEY_NAMES[name])
    if name.startswith("f") and name[1:].isdigit():  # f1..f24
        return ("key", name)
    return ("key", name)


def public_events(events: list[dict]) -> list[dict]:
    """Events without internal fields (e.g. the stashed ``_crop`` frames)."""
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]


class RecordingSession:
    """One recording session: normalized events + click-time crops."""

    def __init__(self, session_id: str, capture: Capture,
                 esc_callback: Optional[Callable[[], None]] = None) -> None:
        self.id = session_id
        self.capture = capture
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.started_mono = time.monotonic()
        self.started_wall = time.time()
        self.duration_s = 0.0
        self.stopped = False
        self.held: set[str] = set()
        self.last_window: Optional[str] = None
        self._esc_callback = esc_callback

    # -- event plumbing ---------------------------------------------------

    def _t(self) -> float:
        return round(time.monotonic() - self.started_mono, 3)

    def _add(self, event: dict) -> None:
        with self.lock:
            if not self.stopped:
                self.events.append(event)

    def _window_tick(self) -> None:
        title = _foreground_title()
        if title and title != self.last_window:
            self.last_window = title
            self._add({"t": self._t(), "kind": "window", "title": title})

    def grab_crop(self, x: int, y: int) -> Optional[np.ndarray]:
        """~80x80 crop around (x, y) from a click-time screenshot, clamped."""
        try:
            frame = self.capture.grab()
        except Exception as exc:
            logger.debug("click-time screenshot failed: %s", exc)
            return None
        h, w = frame.shape[:2]
        size = min(CROP_SIZE, w, h)
        x0 = min(max(0, x - size // 2), w - size)
        y0 = min(max(0, y - size // 2), h - size)
        return frame[y0 : y0 + size, x0 : x0 + size].copy()

    # -- pynput callbacks ---------------------------------------------------

    def on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed:  # record presses, not releases
            return
        self._window_tick()
        button_name = str(button).rsplit(".", 1)[-1].lower()
        event: dict = {
            "t": self._t(),
            "kind": "click",
            "x": int(x),
            "y": int(y),
            "button": button_name,
            "window": self.last_window or "",
        }
        crop = self.grab_crop(int(x), int(y))
        if crop is not None:
            event["_crop"] = crop
        self._add(event)

    def on_press(self, key) -> None:
        category, name = _classify_key(key)
        if category == "modifier":
            self.held.add(name)
            return
        # Esc-stop rule: the FIRST bare Esc (no other key held) stops the
        # recording and is NOT recorded. Esc with anything held is recorded.
        if category == "key" and name == "esc" and not self.held:
            if self._esc_callback is not None:
                self._esc_callback()
            return
        mods = sorted((m for m in self.held if m in MODIFIER_ORDER),
                      key=MODIFIER_ORDER.index)
        self._window_tick()
        window = self.last_window or ""
        if category == "char" and not mods:
            self._add({"t": self._t(), "kind": "char", "text": name, "window": window})
        elif category == "key" and name == "space" and not mods:
            # pynput reports the space bar as Key.space; it's typed text
            self._add({"t": self._t(), "kind": "char", "text": " ", "window": window})
        else:
            combo = mods + [name]
            self._add({"t": self._t(), "kind": "key", "key": "+".join(combo),
                       "window": window})
        self.held.add(name)

    def on_release(self, key) -> None:
        _, name = _classify_key(key)
        self.held.discard(name)

    # -- lifecycle ----------------------------------------------------------

    def finish(self) -> None:
        with self.lock:
            self.stopped = True
            self.duration_s = round(time.monotonic() - self.started_mono, 2)

    @property
    def event_count(self) -> int:
        with self.lock:
            return len(self.events)

    def elapsed_s(self) -> float:
        return round(time.monotonic() - self.started_mono, 2)


class AlreadyRecording(Exception):
    pass


class NoActiveRecording(Exception):
    pass


class RecorderManager:
    """Owns the active recording session and finished ones awaiting convert."""

    def __init__(self, capture: Capture) -> None:
        self.capture = capture
        self.active: Optional[RecordingSession] = None
        self.sessions: dict[str, RecordingSession] = {}
        self._listeners: list = []
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    def start(self) -> str:
        with self._lock:
            if self.active is not None:
                raise AlreadyRecording("a recording is already in progress")
            mouse, keyboard = _pynput()
            if mouse is None or keyboard is None:
                raise RuntimeError(
                    f"input recording is unavailable (pynput: {_PYNPUT_ERROR})"
                )
            session = RecordingSession(
                f"{uuid.uuid4().hex[:8]}", self.capture, esc_callback=self._esc_stop
            )
            listeners = [
                mouse.Listener(on_click=session.on_click),
                keyboard.Listener(on_press=session.on_press,
                                  on_release=session.on_release),
            ]
            for listener in listeners:
                listener.start()
            self._listeners = listeners
            self.active = session
            logger.info("recording started session=%s", session.id)
            return session.id

    def _esc_stop(self) -> None:
        # never stop listeners from inside a listener callback thread
        threading.Thread(target=self._safe_stop, daemon=True).start()

    def _safe_stop(self) -> None:
        try:
            self.stop()
        except NoActiveRecording:
            pass

    def stop(self) -> RecordingSession:
        with self._lock:
            session = self.active
            if session is None:
                raise NoActiveRecording("no recording in progress")
            self.active = None
            listeners, self._listeners = self._listeners, []
        for listener in listeners:
            try:
                listener.stop()
            except Exception as exc:
                logger.debug("listener stop failed: %s", exc)
        session.finish()
        with self._lock:
            self.sessions[session.id] = session
        logger.info("recording stopped session=%s events=%d",
                    session.id, session.event_count)
        return session

    def status(self) -> dict:
        with self._lock:
            session = self.active
        if session is None:
            return {"recording": False, "event_count": 0, "elapsed_s": 0.0}
        return {
            "recording": True,
            "session_id": session.id,
            "event_count": session.event_count,
            "elapsed_s": session.elapsed_s(),
        }

    def get(self, session_id: str) -> RecordingSession:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def discard(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self.sessions:
                raise KeyError(session_id)
            del self.sessions[session_id]
        logger.info("recording discarded session=%s", session_id)

    def consume(self, session_id: str) -> RecordingSession:
        """Fetch a finished session and remove it from the store (convert)."""
        with self._lock:
            if session_id not in self.sessions:
                raise KeyError(session_id)
            return self.sessions.pop(session_id)

    def shutdown(self) -> None:
        try:
            if self.active is not None:
                self.stop()
        except Exception:  # pragma: no cover - atexit best effort
            pass
