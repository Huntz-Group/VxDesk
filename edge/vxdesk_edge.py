#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VxDesk legacy edge client — ONE file, stdlib only, Python 2.7 AND 3.4+.

Polls the VxDesk hub over plain HTTP+JSON (edge transport), executes ONLY
``shell`` commands, and reports stdout/stderr/exit code back. ``run_workflow``
commands are refused and reported as ``ok:false, error:"unsupported"`` (this
client has no workflow engine).

SECURITY / XP NOTE: XP-era Python ships TLS stacks (SSLv3/TLS1.0) that modern
servers no longer accept, and this client cannot fix that. Prefer plain HTTP on
a trusted LAN, or wrap the connection with stunnel. ``insecure_tls = true``
disables certificate verification (Python 3: unverified SSL context; Python 2:
best effort) — only ever use it on a network you fully trust.

Config (INI, next to this file as ``vxdesk_edge.ini`` or via ``--config``):

    [edge]
    server = http://192.168.1.10:8765
    agent_id = xp-pos-01
    token = <minted on the hub>
    interval = 5
    insecure_tls = false

Flags: ``--once`` (single poll cycle, for testing/schedulers), ``--config``.
"""

import json
import os
import subprocess
import sys
import time

PY2 = sys.version_info[0] == 2

if PY2:
    from urllib2 import Request, urlopen
    from urllib import urlencode
    import ConfigParser as configparser
else:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    import configparser

VERSION = "0.1.0"
BACKOFF_MIN = 2.0
BACKOFF_MAX = 60.0
SHELL_TIMEOUT = 300


def log(message):
    sys.stderr.write("[vxdesk-edge] %s\n" % message)
    sys.stderr.flush()


def http_json(method, url, payload=None, timeout=30, insecure_tls=False):
    """Minimal JSON-over-HTTP helper (urllib2/urllib shim)."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    if PY2 and method == "POST" and data is not None:
        pass  # urllib2 POSTs automatically when data is present
    context = None
    if not PY2 and url.startswith("https") and insecure_tls:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if PY2:
        response = urlopen(req, timeout=timeout)
    else:
        response = urlopen(req, timeout=timeout, context=context)
    body = response.read().decode("utf-8")
    return json.loads(body)


def load_config(path):
    defaults = {
        "server": "http://127.0.0.1:8765",
        "agent_id": "",
        "token": "",
        "interval": "5",
        "insecure_tls": "false",
    }
    parser = configparser.ConfigParser()
    if os.path.isfile(path):
        parser.read(path)
    config = dict(defaults)
    if parser.has_section("edge"):
        for key in defaults:
            if parser.has_option("edge", key):
                config[key] = parser.get("edge", key)
    if not config["agent_id"]:
        import socket
        config["agent_id"] = socket.gethostname().lower()
    return config


def execute_shell(command_id, shell_command):
    """Run a shell command; returns a result dict."""
    if not shell_command:
        return {"command_id": command_id, "ok": False,
                "output": None, "error": "empty shell command"}
    try:
        proc = subprocess.Popen(
            shell_command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = proc.communicate(timeout=SHELL_TIMEOUT)
        except TypeError:  # Python 2: no timeout support
            stdout, stderr = proc.communicate()
        if not isinstance(stdout, str):
            stdout = stdout.decode("utf-8", "replace")
            stderr = stderr.decode("utf-8", "replace")
        ok = proc.returncode == 0
        return {
            "command_id": command_id,
            "ok": ok,
            "output": {"stdout": stdout[-4000:], "stderr": stderr[-4000:],
                       "exit_code": proc.returncode},
            "error": None if ok else "exit code %s" % proc.returncode,
        }
    except Exception as exc:
        return {"command_id": command_id, "ok": False,
                "output": None, "error": str(exc)}


def run_cycle(config, state):
    """One poll cycle: poll -> execute -> report. Returns True on success."""
    server = config["server"].rstrip("/")
    agent_id = config["agent_id"]
    token = config["token"]
    insecure = config.get("insecure_tls", "false").lower() == "true"

    if not state.get("hello_done"):
        hello = http_json("POST", server + "/api/edge/hello", {
            "agent_id": agent_id,
            "name": config.get("name", agent_id),
            "token": token,
            "caps": {"os": "legacy", "engine": False, "workflows": False},
        }, insecure_tls=insecure)
        if not hello.get("ok"):
            log("hello rejected: %s" % hello)
            return False
        state["hello_done"] = True
        state["agent_id"] = hello.get("agent", {}).get("agent_id", agent_id)

    agent_id = state["agent_id"]
    query = urlencode({"agent_id": agent_id, "token": token, "wait": "0"})
    polled = http_json("GET", server + "/api/edge/poll?" + query,
                       insecure_tls=insecure)
    commands = polled.get("commands") or []

    events = []
    results = []
    for command in commands:
        command_id = command.get("command_id", "")
        kind = command.get("command")
        if kind == "shell":
            shell_command = command.get("shell") or command.get("shell_command")
            log("running shell command %s: %r" % (command_id, shell_command))
            events.append({"kind": "status", "ts": time.time(),
                           "message": "executing %s" % command_id})
            results.append(execute_shell(command_id, shell_command))
        else:
            # run_workflow and anything else: refuse — no engine here
            log("refusing unsupported command %s (%s)" % (command_id, kind))
            results.append({"command_id": command_id, "ok": False,
                            "output": None, "error": "unsupported"})

    if events or results:
        http_json("POST", server + "/api/edge/report", {
            "agent_id": agent_id,
            "token": token,
            "events": events,
            "results": results,
        }, insecure_tls=insecure)
    return True


def main(argv):
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "vxdesk_edge.ini")
    once = False
    i = 0
    while i < len(argv):
        if argv[i] == "--config" and i + 1 < len(argv):
            config_path = argv[i + 1]
            i += 2
        elif argv[i] == "--once":
            once = True
            i += 1
        else:
            sys.stderr.write("unknown argument: %s\n" % argv[i])
            return 2
    config = load_config(config_path)
    interval = float(config.get("interval", "5"))
    state = {}
    backoff = BACKOFF_MIN

    log("edge client %s polling %s as %s"
        % (VERSION, config["server"], config["agent_id"]))
    while True:
        try:
            if run_cycle(config, state):
                backoff = BACKOFF_MIN
            else:
                raise RuntimeError("cycle failed")
        except Exception as exc:
            log("poll failed: %s (retry in %.0fs)" % (exc, backoff))
            state["hello_done"] = False
            time.sleep(backoff)
            backoff = min(BACKOFF_MAX, backoff * 2)
            if once:
                return 1
            continue
        if once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
