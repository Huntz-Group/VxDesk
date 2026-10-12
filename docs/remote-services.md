# VxDesk — Remote Services contract (host ↔ agents)

VxDesk can act as a **hub**: remote machines connect in (or poll), receive workflow-run
commands, execute them locally, and report all activity back. Three transports:

| Transport | Endpoint | Client | Notes |
|---|---|---|---|
| WebSocket | `ws(s)://host:8765/ws/remote` | full agent | push, realtime, wss when TLS configured |
| TCP | `host:8766` (configurable) | full agent / tiny clients | JSON-lines, length-free (one JSON object per line) |
| Edge poll | `http(s)://host:8765/api/edge/*` | legacy edge client | plain HTTP+JSON, stdlib-only, XP-Embedded-friendly |

**Security model**: remote access is OFF by default. Enabling it requires a bind address
choice (127.0.0.1 default) and generates a hub token. Every agent authenticates with
`token` (hello message / `X-VxDesk-Token` header / `?token=` query — all accepted,
because the oldest clients can barely set headers). Tokens are per-agent, revocable.
TLS is optional: user supplies cert/key paths in settings (`scripts/make_dev_cert.ps1`
generates a dev self-signed pair); when set, uvicorn serves HTTPS+WSS.

## Message protocol (ws + tcp, one JSON object per message/line)

Agent → hub:
```json
{"type": "hello", "agent_id": "mach-01", "name": "Shop floor PC", "token": "…",
 "caps": {"os": "windows", "engine": true, "workflows": true}}
{"type": "event", "kind": "log|status|run_started|run_finished", "message": "…", "run_id": "…", "ts": 1234.5}
{"type": "result", "command_id": "cmd_…", "ok": true, "output": {…}, "error": null}
{"type": "pong", "ts": 1234.5}
```
Hub → agent:
```json
{"type": "welcome", "ok": true, "error": null}
{"type": "command", "command_id": "cmd_…", "command": "run_workflow",
 "workflow_id": "wf_…", "workflow": {…full graph JSON…}, "dry_run": false}
{"type": "ping", "ts": 1234.5}
```
Rules: first agent message MUST be `hello`; bad token → `{"type":"welcome","ok":false,"error":"…"}` + close.
`workflow` is the FULL graph (self-contained — agents never call back for it).

## Edge polling API (legacy-friendly: HTTP/1.0-safe, no chunked requirements)

- `POST /api/edge/hello` body `{agent_id, name, token, caps}` → `{ok, agent}` (upserts agent)
- `GET  /api/edge/poll?agent_id=…&token=…&wait=0` → `{commands: […same command shape…]}`
  (`wait` up to 25s = long-poll; 0 = instant)
- `POST /api/edge/report` body `{agent_id, token, events: […], results: […]}` → `{ok}`
- `GET  /api/edge/ping` → `{ok: true, server: "vxdesk", version}` (connectivity check)

Edge v1 command types: `run_workflow` (full agents) and `shell` (`{command: "…"}` —
the legacy edge client executes it and reports stdout/stderr/exit code). Legacy client
MUST refuse `run_workflow` (no engine) and report `ok:false, error:"unsupported"`.

## Hub management REST (used by the Remote page)

- `GET  /api/remote/status` → `{enabled, bind, transports: {ws: true, tcp: true, edge: true}, tcp_port, tls: {enabled, cert, key}, agents_online, agents_total}`
- `PUT  /api/remote/settings` `{enabled?, bind?, transports?, tcp_port?, tls?}` → status (takes effect immediately where possible; port/TLS changes report `restart_required: true`)
- `GET  /api/remote/agents` → `[{agent_id, name, online, transport, last_seen, caps, address}]`
- `POST /api/remote/agents` `{name}` → `{agent_id, token}` (pre-register + mint token; token shown ONCE)
- `DELETE /api/remote/agents/{id}` → revokes token, disconnects
- `POST /api/remote/agents/{id}/run` `{workflow_id, dry_run?}` → `{command_id}` (queued/pushed; 409 if agent offline)
- `GET  /api/remote/activity?limit=200` → `[{ts, agent_id, kind, message, run_id?, command_id?, ok?}]` newest-first, capped at 1000 entries, persisted to `workflows/.runs/remote-activity.jsonl`

## Full agent (`python -m vxdesk.agent`)

Flags: `--server ws://host:8765` (or `tcp://host:8766`), `--token`, `--agent-id`,
`--name`, `--dry-run-default`. Reconnect with backoff (1s→30s cap). Executes
`run_workflow` with the embedded engine (workflow JSON from the command), streams
`run_started`/`log`/`run_finished` events + final `result`. Windows-service friendly:
no console interaction, logs to file. `scripts/install-agent-service.ps1` (NSSM-free:
Task Scheduler at boot, `powershell -WindowStyle Hidden`).

## Legacy edge client (`edge/vxdesk_edge.py`)

ONE file, stdlib only, Python 2.7 AND 3.4+ compatible (no f-strings, no pathlib,
`urllib2`/`urllib` shim). INI config (`server`, `agent_id`, `token`, `interval`,
`insecure_tls`). Poll loop with backoff on failure. Executes only `shell` commands;
reports events/results each cycle. `--once` flag (single cycle, for testing/schedulers).
XP note in its docstring: old TLS — prefer plain HTTP on a trusted LAN or stunnel.

## Testing requirements

- Hub: registry, token mint/revoke, queue, activity cap, settings persistence.
- WS: real ws client (in-proc uvicorn) — hello/auth fail/command/result round trip.
- TCP: socket client round trip.
- Edge: TestClient-driven hello/poll(wait=0)/report; `shell` command delivered;
  legacy client file executed with `--once` in a subprocess against a live server.
- E2E: live hub + full agent over WS running the safe "Welcome tour" workflow dry-run,
  activity visible via REST.
