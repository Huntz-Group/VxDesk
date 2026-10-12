"""VxDesk full remote agent — runs on a remote machine, driven by the hub.

Usage:
    python -m vxdesk.agent --server ws://host:8765 --token T --agent-id A --name "PC"
    python -m vxdesk.agent --server tcp://host:8766 ...
    python -m vxdesk.agent --server wss://host:8767 ...   (TLS listener)

Flags: ``--dry-run-default`` forces dry_run on every workflow run.
Reconnects with backoff (1s -> 30s cap). Executes ``run_workflow`` commands with
the embedded WorkflowEngine (the workflow graph is inline in the command) and
``shell`` commands via subprocess; streams run_started/log/run_finished events
and a final result. Windows-service friendly: no console interaction, logs to a
file. SIGTERM/SIGINT stop the agent cleanly.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

from . import __version__
from .engine.executor import Run, WorkflowEngine
from .paths import ROOT

logger = logging.getLogger("vxdesk.agent")

BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 30.0
SHELL_TIMEOUT_S = 300


def _new_run_id() -> str:
    import uuid

    return f"run_{uuid.uuid4().hex[:12]}"


class Agent:
    def __init__(self, server: str, token: str, agent_id: str, name: str,
                 dry_run_default: bool = False) -> None:
        parsed = urlparse(server if "://" in server else f"ws://{server}")
        self.transport = parsed.scheme or "ws"
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or (8766 if self.transport == "tcp" else 8765)
        self.token = token
        self.agent_id = agent_id
        self.name = name
        self.dry_run_default = dry_run_default
        self.stop_event = threading.Event()
        self._engine: Optional[WorkflowEngine] = None
        self._engine_lock = threading.Lock()
        self._send_lock = threading.Lock()

    # -- engine --------------------------------------------------------------

    @property
    def engine(self) -> WorkflowEngine:
        with self._engine_lock:
            if self._engine is None:
                self._engine = WorkflowEngine()
            return self._engine

    def _hello(self) -> dict:
        return {
            "type": "hello",
            "agent_id": self.agent_id,
            "name": self.name,
            "token": self.token,
            "caps": {"os": "windows", "engine": True, "workflows": True},
        }

    # -- command execution ------------------------------------------------------

    def execute(self, command: dict, send) -> None:
        kind = command.get("command")
        command_id = command.get("command_id", "?")
        try:
            if kind == "run_workflow":
                self._execute_workflow(command, send)
            elif kind == "shell":
                self._execute_shell(command, send)
            else:
                send({"type": "result", "command_id": command_id, "ok": False,
                      "output": None, "error": f"unsupported command: {kind}"})
        except Exception as exc:
            logger.exception("command %s crashed", command_id)
            send({"type": "result", "command_id": command_id, "ok": False,
                  "output": None, "error": str(exc)})

    def _execute_workflow(self, command: dict, send) -> None:
        command_id = command.get("command_id", "?")
        workflow = command.get("workflow")
        if not isinstance(workflow, dict) or not workflow.get("nodes"):
            send({"type": "result", "command_id": command_id, "ok": False,
                  "output": None, "error": "command carries no workflow graph"})
            return
        dry_run = bool(command.get("dry_run")) or self.dry_run_default
        run_id = _new_run_id()
        run = Run(run_id, workflow.get("id", command.get("workflow_id", "?")), dry_run)

        send({"type": "event", "kind": "run_started", "run_id": run_id,
              "message": f"run started ({workflow.get('name', run_id)})"
                         + (" [dry-run]" if dry_run else ""),
              "ts": time.time()})

        def emit(event: dict) -> None:
            if event.get("event") == "log":
                send({"type": "event", "kind": "log", "run_id": run_id,
                      "message": str(event.get("message", "")), "ts": time.time()})

        logger.info("executing workflow %s as %s (dry_run=%s)",
                    workflow.get("name"), run_id, dry_run)
        self.engine.execute(run, workflow, emit=emit)
        ok = run.status == "success"
        send({"type": "event", "kind": "run_finished", "run_id": run_id,
              "message": f"run {run.status}" + (f": {run.error}" if run.error else ""),
              "ts": time.time()})
        send({"type": "result", "command_id": command_id, "ok": ok,
              "output": {"run_id": run_id, "status": run.status,
                         "error": run.error, "dry_run": dry_run},
              "error": run.error if not ok else None})

    def _execute_shell(self, command: dict, send) -> None:
        command_id = command.get("command_id", "?")
        shell_cmd = command.get("shell") or command.get("shell_command") or ""
        if not shell_cmd:
            send({"type": "result", "command_id": command_id, "ok": False,
                  "output": None, "error": "empty shell command"})
            return
        logger.info("executing shell command %s: %r", command_id, shell_cmd)
        try:
            proc = subprocess.run(
                shell_cmd, shell=True, capture_output=True, text=True,
                timeout=SHELL_TIMEOUT_S,
            )
            ok = proc.returncode == 0
            send({"type": "result", "command_id": command_id, "ok": ok,
                  "output": {"stdout": proc.stdout[-4000:],
                             "stderr": proc.stderr[-4000:],
                             "exit_code": proc.returncode},
                  "error": None if ok else f"exit code {proc.returncode}"})
        except subprocess.TimeoutExpired:
            send({"type": "result", "command_id": command_id, "ok": False,
                  "output": None, "error": f"timeout after {SHELL_TIMEOUT_S}s"})

    # -- transports ---------------------------------------------------------------

    def run(self) -> int:
        backoff = BACKOFF_MIN_S
        while not self.stop_event.is_set():
            try:
                if self.transport == "tcp":
                    self._run_tcp()
                else:
                    self._run_ws()
                backoff = BACKOFF_MIN_S  # clean disconnect: reset backoff
            except KeyboardInterrupt:
                break
            except Exception as exc:
                logger.warning("connection failed: %s", exc)
            if self.stop_event.is_set():
                break
            logger.info("reconnecting in %.0fs…", backoff)
            self.stop_event.wait(backoff)
            backoff = min(BACKOFF_MAX_S, backoff * 2)
        return 0

    def _run_ws(self) -> None:
        import asyncio

        asyncio.run(self._run_ws_async())

    async def _run_ws_async(self) -> None:
        import asyncio

        import websockets

        scheme = "wss" if self.transport == "wss" else "ws"
        url = f"{scheme}://{self.host}:{self.port}/ws/remote"
        outbox: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def send(obj: dict) -> None:
            loop.call_soon_threadsafe(outbox.put_nowait, obj)

        logger.info("connecting to %s", url)
        async with websockets.connect(url, ping_interval=None) as ws:
            await ws.send(json.dumps(self._hello()))
            welcome = json.loads(await ws.recv())
            if not welcome.get("ok"):
                raise RuntimeError(f"hub rejected hello: {welcome.get('error')}")
            self.agent_id = welcome.get("agent_id", self.agent_id)
            logger.info("connected as %s", self.agent_id)

            async def sender() -> None:
                while True:
                    obj = await outbox.get()
                    await ws.send(json.dumps(obj, default=str))

            sender_task = asyncio.ensure_future(sender())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "command":
                        threading.Thread(target=self.execute,
                                         args=(msg, send), daemon=True).start()
                    elif msg_type == "ping":
                        send({"type": "pong", "ts": msg.get("ts")})
                    if self.stop_event.is_set():
                        break
            finally:
                sender_task.cancel()

    def _run_tcp(self) -> None:
        import socket

        logger.info("connecting to tcp://%s:%s", self.host, self.port)
        sock = socket.create_connection((self.host, self.port), timeout=15)
        sock.settimeout(None)
        reader = sock.makefile("r", encoding="utf-8", newline="\n")

        def send(obj: dict) -> None:
            data = (json.dumps(obj, default=str) + "\n").encode("utf-8")
            with self._send_lock:
                sock.sendall(data)

        try:
            send(self._hello())
            welcome = json.loads(reader.readline())
            if not welcome.get("ok"):
                raise RuntimeError(f"hub rejected hello: {welcome.get('error')}")
            self.agent_id = welcome.get("agent_id", self.agent_id)
            logger.info("connected as %s (tcp)", self.agent_id)
            while not self.stop_event.is_set():
                line = reader.readline()
                if not line:
                    break
                msg = json.loads(line)
                msg_type = msg.get("type")
                if msg_type == "command":
                    threading.Thread(target=self.execute,
                                     args=(msg, send), daemon=True).start()
                elif msg_type == "ping":
                    send({"type": "pong", "ts": msg.get("ts")})
        finally:
            try:
                sock.close()
            except OSError:
                pass


def _setup_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "agent.log", maxBytes=1_000_000, backupCount=3,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vxdesk-agent",
                                     description="VxDesk remote agent")
    parser.add_argument("--server", required=True,
                        help="ws://host:8765, wss://host:8767 or tcp://host:8766")
    parser.add_argument("--token", required=True)
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--dry-run-default", action="store_true",
                        help="force dry_run on all workflow runs")
    args = parser.parse_args(argv)

    _setup_logging()
    agent = Agent(
        server=args.server,
        token=args.token,
        agent_id=args.agent_id,
        name=args.name or args.agent_id or "vxdesk-agent",
        dry_run_default=args.dry_run_default,
    )

    def _stop(*_sig: Any) -> None:
        agent.stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):
                pass

    logger.info("vxdesk agent %s starting (server=%s)", __version__, args.server)
    return agent.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
