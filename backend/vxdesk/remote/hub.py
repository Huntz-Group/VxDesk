"""Remote services hub: agent registry, settings, activity log, command queues.

Persistence (all in the data dir — repo root in dev, %LOCALAPPDATA%\\VxDesk
when frozen):

- ``remote-settings.json``  — enabled/bind/transports/tcp_port/tls
- ``remote-agents.json``    — agents with sha256-hashed tokens (plaintext is
  shown exactly once at mint time)
- ``workflows/.runs/remote-activity.jsonl`` — activity log, capped at 1000
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..paths import ROOT, RUNS_DIR, ensure_dirs

logger = logging.getLogger("vxdesk.remote.hub")

ACTIVITY_CAP = 1000
EDGE_ONLINE_WINDOW_S = 120.0  # an edge agent seen within this window counts online

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "bind": "127.0.0.1",
    "transports": {"ws": True, "tcp": True, "edge": True},
    "tcp_port": 8766,
    "tls": {"cert": "", "key": ""},
}


def _now() -> float:
    return time.time()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- settings


class SettingsStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (ROOT / "remote-settings.json")
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        for key in ("enabled", "bind", "tcp_port"):
            if key in data:
                merged[key] = data[key]
        if isinstance(data.get("transports"), dict):
            for t in ("ws", "tcp", "edge"):
                if t in data["transports"]:
                    merged["transports"][t] = bool(data["transports"][t])
        if isinstance(data.get("tls"), dict):
            for k in ("cert", "key"):
                if k in data["tls"]:
                    merged["tls"][k] = str(data["tls"][k])
        return merged

    def save(self, settings: dict) -> None:
        with self._lock:
            self.path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


# --------------------------------------------------------------------- registry


class AgentRegistry:
    """Persisted agent records; tokens are stored as sha256 hashes."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (ROOT / "remote-agents.json")
        self._lock = threading.Lock()
        self._agents: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._agents = {a["agent_id"]: a for a in data.get("agents", [])}
        except Exception:
            self._agents = {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps({"agents": list(self._agents.values())}, indent=2),
            encoding="utf-8",
        )

    def mint(self, name: str) -> tuple[str, str]:
        """Pre-register an agent; returns (agent_id, plaintext token) — once."""
        token = secrets.token_urlsafe(24)
        agent_id = f"agt_{secrets.token_hex(6)}"
        with self._lock:
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "name": name,
                "token_hash": hash_token(token),
                "created_at": _now(),
                "caps": {},
                "last_seen": None,
            }
            self._save()
        return agent_id, token

    def verify(self, token: str) -> Optional[dict]:
        if not token:
            return None
        digest = hash_token(token)
        with self._lock:
            for agent in self._agents.values():
                if agent["token_hash"] == digest:
                    return dict(agent)
        return None

    def upsert_from_hello(self, token: str, agent_id: str, name: str,
                          caps: dict) -> Optional[dict]:
        """Edge hello: verify token, then upsert the claimed agent record."""
        record = self.verify(token)
        if record is None:
            return None
        with self._lock:
            canonical = self._agents[record["agent_id"]]
            if agent_id and agent_id != record["agent_id"]:
                if agent_id not in self._agents:
                    # rebind: the client owns a persistent agent_id (INI config)
                    del self._agents[record["agent_id"]]
                    canonical["agent_id"] = agent_id
                    self._agents[agent_id] = canonical
            if name:
                canonical["name"] = name
            canonical["caps"] = caps or {}
            canonical["last_seen"] = _now()
            self._save()
            return dict(canonical)

    def revoke(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            self._save()
            return True

    def touch(self, agent_id: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is not None:
                agent["last_seen"] = _now()

    def set_fields(self, agent_id: str, **fields) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is not None:
                agent.update(fields)
                self._save()

    def get(self, agent_id: str) -> Optional[dict]:
        with self._lock:
            agent = self._agents.get(agent_id)
            return dict(agent) if agent else None

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(a) for a in self._agents.values()]


# --------------------------------------------------------------------- activity


class ActivityLog:
    """JSONL activity log, capped at 1000 entries, newest-first reads."""

    def __init__(self, path: Optional[Path] = None) -> None:
        ensure_dirs()
        self.path = path or (RUNS_DIR / "remote-activity.jsonl")
        self._lock = threading.Lock()
        self._count = self._count_lines()

    def _count_lines(self) -> int:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except FileNotFoundError:
            return 0
        except Exception:
            return 0

    def add(self, entry: dict) -> None:
        entry = {"ts": _now(), **entry}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._count += 1
            if self._count > ACTIVITY_CAP + 200:
                self._trim_locked()

    def _trim_locked(self) -> None:
        lines = self._read_lines_locked()[-ACTIVITY_CAP:]
        self.path.write_text("".join(lines), encoding="utf-8")
        self._count = len(lines)

    def _read_lines_locked(self) -> list[str]:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return [l for l in fh if l.strip()]
        except FileNotFoundError:
            return []

    def read(self, limit: int = 200) -> list[dict]:
        with self._lock:
            lines = self._read_lines_locked()
        out = []
        for line in reversed(lines[-max(1, min(limit, ACTIVITY_CAP)):]):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


# --------------------------------------------------------------------- hub


class LiveConnection:
    """A push channel to an online agent (ws or tcp). Thread-safe send."""

    def __init__(self, transport: str, address: str,
                 send: Callable[[dict], None], close: Callable[[], None]) -> None:
        self.transport = transport
        self.address = address
        self._send = send
        self._close = close

    def send_json(self, obj: dict) -> None:
        self._send(obj)

    def close(self) -> None:
        self._close()


class AgentOfflineError(Exception):
    pass


class Hub:
    """Coordinates registry, settings, activity, queues and live connections."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        if data_dir is not None:
            data_dir = Path(data_dir)
            self.settings_store = SettingsStore(data_dir / "remote-settings.json")
            self.registry = AgentRegistry(data_dir / "remote-agents.json")
            self.activity = ActivityLog(data_dir / "remote-activity.jsonl")
        else:
            self.settings_store = SettingsStore()
            self.registry = AgentRegistry()
            self.activity = ActivityLog()
        self._lock = threading.Lock()
        self._live: dict[str, LiveConnection] = {}
        self._queues: dict[str, list[dict]] = {}
        self.results: dict[str, dict] = {}
        self._condition = threading.Condition()  # signaled when commands arrive

    # -- settings -----------------------------------------------------------

    def settings(self) -> dict:
        return self.settings_store.load()

    def update_settings(self, patch: dict) -> dict:
        settings = self.settings()
        if "enabled" in patch:
            settings["enabled"] = bool(patch["enabled"])
        if "bind" in patch and patch["bind"]:
            settings["bind"] = str(patch["bind"])
        if "tcp_port" in patch and patch["tcp_port"]:
            settings["tcp_port"] = int(patch["tcp_port"])
        if isinstance(patch.get("transports"), dict):
            for t in ("ws", "tcp", "edge"):
                if t in patch["transports"]:
                    settings["transports"][t] = bool(patch["transports"][t])
        if isinstance(patch.get("tls"), dict):
            for k in ("cert", "key"):
                if k in patch["tls"]:
                    settings["tls"][k] = str(patch["tls"][k])
        self.settings_store.save(settings)
        if settings["enabled"] and settings["bind"] in ("0.0.0.0", "::"):
            logger.warning(
                "REMOTE SERVICES ENABLED ON %s — agents on other machines can "
                "drive this desktop. Use only on trusted networks.",
                settings["bind"],
            )
        return settings

    # -- connections ----------------------------------------------------------

    def connect(self, agent_id: str, conn: LiveConnection) -> None:
        with self._lock:
            old = self._live.pop(agent_id, None)
            self._live[agent_id] = conn
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.registry.set_fields(agent_id, transport=conn.transport)
        self.registry.touch(agent_id)
        self.log_activity(agent_id, "status", f"online via {conn.transport}")

    def disconnect(self, agent_id: str, conn: LiveConnection) -> None:
        with self._lock:
            if self._live.get(agent_id) is conn:
                del self._live[agent_id]
        self.registry.set_fields(agent_id, transport=None)
        self.registry.touch(agent_id)
        self.log_activity(agent_id, "status", "offline")

    def is_online(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id in self._live:
                return True
        agent = self.registry.get(agent_id)
        if agent and agent.get("last_seen"):
            # only edge (polling) agents count last_seen as "online"
            return (agent.get("transport") == "edge"
                    and (_now() - agent["last_seen"]) < EDGE_ONLINE_WINDOW_S)
        return False

    # -- commands -----------------------------------------------------------

    def dispatch(self, agent_id: str, command: dict) -> str:
        """Push to a live agent, else queue for edge poll. Returns command_id."""
        command.setdefault("command_id", f"cmd_{secrets.token_hex(6)}")
        command = {"type": "command", **command}
        with self._lock:
            conn = self._live.get(agent_id)
        if conn is not None:
            conn.send_json(command)
            self.log_activity(agent_id, "status",
                              f"command {command['command_id']} pushed "
                              f"({command.get('command')})",
                              command_id=command["command_id"])
        elif self.is_online(agent_id):
            with self._condition:
                self._queues.setdefault(agent_id, []).append(command)
                self._condition.notify_all()
            self.log_activity(agent_id, "status",
                              f"command {command['command_id']} queued "
                              f"({command.get('command')})",
                              command_id=command["command_id"])
        else:
            raise AgentOfflineError(f"agent {agent_id} is offline")
        return command["command_id"]

    def queue_command(self, agent_id: str, command: dict) -> str:
        """Queue unconditionally (for the next edge poll), even if offline."""
        command.setdefault("command_id", f"cmd_{secrets.token_hex(6)}")
        with self._condition:
            self._queues.setdefault(agent_id, []).append(
                {"type": "command", **command})
            self._condition.notify_all()
        return command["command_id"]

    def poll_commands(self, agent_id: str, wait_s: float = 0.0) -> list[dict]:
        """Drain the queue; long-poll up to ``wait_s`` for new commands."""
        deadline = _now() + max(0.0, min(wait_s, 25.0))
        with self._condition:
            while True:
                queue = self._queues.get(agent_id)
                if queue:
                    commands = list(queue)
                    queue.clear()
                    return commands
                remaining = deadline - _now()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)

    # -- intake ----------------------------------------------------------------

    def handle_event(self, agent_id: str, msg: dict) -> None:
        self.registry.touch(agent_id)
        self.log_activity(
            agent_id,
            str(msg.get("kind", "log")),
            str(msg.get("message", "")),
            run_id=msg.get("run_id"),
        )

    def handle_result(self, agent_id: str, msg: dict) -> None:
        self.registry.touch(agent_id)
        command_id = str(msg.get("command_id", ""))
        ok = bool(msg.get("ok"))
        self.results[command_id] = {
            "agent_id": agent_id, "ok": ok,
            "output": msg.get("output"), "error": msg.get("error"),
            "ts": _now(),
        }
        summary = "ok" if ok else f"failed: {msg.get('error')}"
        self.log_activity(agent_id, "result",
                          f"command {command_id} {summary}",
                          command_id=command_id, ok=ok)

    def log_activity(self, agent_id: str, kind: str, message: str,
                     run_id: Any = None, command_id: Any = None,
                     ok: Any = None) -> None:
        entry: dict[str, Any] = {"agent_id": agent_id, "kind": kind,
                                 "message": message}
        if run_id:
            entry["run_id"] = run_id
        if command_id:
            entry["command_id"] = command_id
        if ok is not None:
            entry["ok"] = bool(ok)
        self.activity.add(entry)

    # -- views ------------------------------------------------------------------

    def agents_view(self) -> list[dict]:
        out = []
        with self._lock:
            live = dict(self._live)
        for agent in self.registry.all():
            conn = live.get(agent["agent_id"])
            online = self.is_online(agent["agent_id"])
            out.append({
                "agent_id": agent["agent_id"],
                "name": agent.get("name", ""),
                "online": online,
                "transport": conn.transport if conn else (
                    agent.get("transport") if online else None),
                "last_seen": agent.get("last_seen"),
                "caps": agent.get("caps", {}),
                "address": conn.address if conn else None,
            })
        return out

    def status_view(self, running_bind: str) -> dict:
        settings = self.settings()
        tls = settings["tls"]
        view = {
            "enabled": settings["enabled"],
            "bind": settings["bind"],
            "transports": dict(settings["transports"]),
            "tcp_port": settings["tcp_port"],
            "tls": {
                "enabled": bool(tls.get("cert") and tls.get("key")),
                "cert": tls.get("cert", ""),
                "key": tls.get("key", ""),
            },
            "agents_online": sum(1 for a in self.agents_view() if a["online"]),
            "agents_total": len(self.registry.all()),
            "restart_required": settings["bind"] != running_bind,
        }
        return view
