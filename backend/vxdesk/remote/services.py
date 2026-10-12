"""Remote transport listeners: TCP JSON-lines server + optional TLS listener.

Lifecycle follows the remote settings: ``RemoteServices.apply()`` is called on
app startup and after every settings change. The TCP server binds the
configured address immediately; the TLS listener (a second uvicorn serving
only the remote routes over HTTPS/WSS) runs on the main port + 2 (8767 by
default) so the local UI keeps plain HTTP on the main port.
"""

from __future__ import annotations

import json
import logging
import socketserver
import threading
import time
from pathlib import Path
from typing import Optional

from .hub import Hub, LiveConnection
from .routes import register_remote_routes

logger = logging.getLogger("vxdesk.remote.services")

TLS_PORT_OFFSET = 2  # main 8765 -> TLS 8767 (8766 is the default TCP port)


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class _TCPHandler(socketserver.StreamRequestHandler):
    """JSON-lines: hello-first auth, then events/results/pong in, commands out."""

    hub: Hub = None  # set by RemoteServices before serving

    def handle(self) -> None:
        hub = self.hub
        wlock = threading.Lock()

        def write(obj: dict) -> None:
            data = (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")
            with wlock:
                self.wfile.write(data)
                self.wfile.flush()

        try:
            line = self.rfile.readline()
            if not line:
                return
            hello = json.loads(line.decode("utf-8", "replace"))
            if hello.get("type") != "hello":
                write({"type": "welcome", "ok": False,
                       "error": "first message must be hello"})
                return
            record = hub.registry.upsert_from_hello(
                str(hello.get("token", "")),
                str(hello.get("agent_id", "") or ""),
                str(hello.get("name", "") or ""),
                hello.get("caps") if isinstance(hello.get("caps"), dict) else {},
            )
            if record is None:
                write({"type": "welcome", "ok": False, "error": "invalid token"})
                return
            agent_id = record["agent_id"]
            address = f"{self.client_address[0]}:{self.client_address[1]}"
            conn = LiveConnection("tcp", address, write,
                                  lambda: self.request.close())
            hub.connect(agent_id, conn)
            write({"type": "welcome", "ok": True, "error": None, "agent_id": agent_id})
            logger.info("agent %s connected via tcp from %s", agent_id, address)
            try:
                while True:
                    line = self.rfile.readline()
                    if not line:
                        break
                    try:
                        msg = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    msg_type = msg.get("type")
                    if msg_type == "event":
                        hub.handle_event(agent_id, msg)
                    elif msg_type == "result":
                        hub.handle_result(agent_id, msg)
                    elif msg_type == "pong":
                        hub.registry.touch(agent_id)
            finally:
                hub.disconnect(agent_id, conn)
                logger.info("agent %s disconnected (tcp)", agent_id)
        except (ConnectionError, OSError):
            pass
        except Exception as exc:
            logger.warning("tcp handler error: %s", exc)


class RemoteServices:
    """Owns the TCP and TLS listeners; lifecycle follows the settings."""

    def __init__(self, hub: Hub, main_port: int = 8765) -> None:
        self.hub = hub
        self.main_port = main_port
        self._tcp_server: Optional[_ThreadingTCPServer] = None
        self._tcp_thread: Optional[threading.Thread] = None
        self._tls_server = None
        self._tls_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    # -- lifecycle -----------------------------------------------------------

    def apply(self) -> None:
        """Start/stop listeners to match the current settings."""
        settings = self.hub.settings()
        with self._lock:
            self._apply_tcp(settings)
            self._apply_tls(settings)
            if settings["enabled"] and self._heartbeat_thread is None:
                self._heartbeat_stop.clear()
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, name="vxdesk-remote-ping",
                    daemon=True)
                self._heartbeat_thread.start()

    def shutdown(self) -> None:
        with self._lock:
            self._stop_tcp_locked()
            self._stop_tls_locked()
            self._heartbeat_stop.set()

    # -- tcp -------------------------------------------------------------------

    def _apply_tcp(self, settings: dict) -> None:
        want = settings["enabled"] and settings["transports"].get("tcp", False)
        running = self._tcp_server is not None
        running_addr = getattr(self, "_tcp_addr", None)
        want_addr = (settings["bind"], int(settings["tcp_port"]))
        if want and running and running_addr == want_addr:
            return
        self._stop_tcp_locked()
        if not want:
            return
        handler = type("BoundTCPHandler", (_TCPHandler,), {"hub": self.hub})
        try:
            server = _ThreadingTCPServer(want_addr, handler)
        except OSError as exc:
            logger.error("remote TCP server could not bind %s:%s — %s",
                         want_addr[0], want_addr[1], exc)
            return
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.5},
                                  name="vxdesk-remote-tcp", daemon=True)
        thread.start()
        self._tcp_server = server
        self._tcp_thread = thread
        self._tcp_addr = want_addr
        logger.info("remote TCP listener on %s:%s", *want_addr)

    def _stop_tcp_locked(self) -> None:
        if self._tcp_server is not None:
            try:
                self._tcp_server.shutdown()
                self._tcp_server.server_close()
            except Exception:
                pass
            self._tcp_server = None
            self._tcp_thread = None
            self._tcp_addr = None

    # -- tls -------------------------------------------------------------------

    def _apply_tls(self, settings: dict) -> None:
        tls = settings["tls"]
        cert, key = tls.get("cert", ""), tls.get("key", "")
        want = (settings["enabled"] and cert and key
                and Path(cert).is_file() and Path(key).is_file())
        running = self._tls_server is not None
        if want and running and getattr(self, "_tls_pair", None) == (cert, key):
            return
        self._stop_tls_locked()
        if not want:
            return
        try:
            import uvicorn
            from fastapi import FastAPI

            tls_app = FastAPI(title="VxDesk Remote (TLS)", docs_url=None,
                              redoc_url=None, openapi_url=None)
            register_remote_routes(tls_app, self.hub)
            port = self.main_port + TLS_PORT_OFFSET
            config = uvicorn.Config(
                tls_app, host=settings["bind"], port=port,
                log_level="warning", loop="asyncio",
                ssl_certfile=cert, ssl_keyfile=key,
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run,
                                      name="vxdesk-remote-tls", daemon=True)
            thread.start()
            self._tls_server = server
            self._tls_thread = thread
            self._tls_pair = (cert, key)
            logger.info("remote TLS listener (https/wss) on %s:%s",
                        settings["bind"], port)
        except Exception as exc:
            logger.error("remote TLS listener failed to start: %s", exc)

    def _stop_tls_locked(self) -> None:
        if self._tls_server is not None:
            self._tls_server.should_exit = True
            self._tls_server = None
            self._tls_thread = None
            self._tls_pair = None

    @property
    def tls_port(self) -> Optional[int]:
        return self.main_port + TLS_PORT_OFFSET if self._tls_server else None

    # -- keepalive ------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(30.0):
            with self.hub._lock:
                conns = list(self.hub._live.values())
            for conn in conns:
                try:
                    conn.send_json({"type": "ping", "ts": time.time()})
                except Exception:
                    pass
