#!/usr/bin/env node
/**
 * VxDesk dev orchestrator.
 *
 * `npm run dev` starts BOTH:
 *   1. the Python backend  (uvicorn, 127.0.0.1:8765)
 *   2. the Vite dev server (frontend/, proxies /api + /ws to the backend)
 *
 * CLI args are forwarded to Vite, so `npm run dev -- --port 7100 --host 0.0.0.0`
 * works as expected. `--backend-only` starts just the backend.
 *
 * Both children are killed when this process exits (Ctrl+C) — nothing is
 * left running in the background.
 */
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const ROOT = __dirname ? path.resolve(__dirname, "..") : process.cwd();
const FRONTEND = path.join(ROOT, "frontend");
const VENV_PY = path.join(ROOT, "backend", ".venv", "Scripts", "python.exe");

const args = process.argv.slice(2);
const backendOnly = args.includes("--backend-only");
const viteArgs = args.filter((a) => a !== "--backend-only");
// Default the preview port to 7100 unless the caller overrides it.
if (!viteArgs.some((a, i) => a === "--port" || a.startsWith("--port="))) {
  viteArgs.push("--port", "7100");
}

const children = [];
let shuttingDown = false;

function killAll(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const c of children) {
    try {
      c.kill("SIGTERM");
    } catch {}
  }
  // Give children a moment, then force-exit. Windows SIGTERM on node/python
  // children spawned without a shell terminates the process directly.
  setTimeout(() => process.exit(code ?? 0), 500);
}

process.on("SIGINT", () => killAll(0));
process.on("SIGTERM", () => killAll(0));
process.on("exit", () => {
  for (const c of children) {
    try {
      c.kill("SIGTERM");
    } catch {}
  }
});

function startBackend() {
  if (!fs.existsSync(VENV_PY)) {
    console.error(
      "[vxdesk] backend venv not found at backend/.venv — run `npm run setup` first."
    );
    process.exit(1);
  }
  const py = spawn(
    VENV_PY,
    [
      "-m",
      "uvicorn",
      "vxdesk.server.app:create_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      "8765",
    ],
    { cwd: path.join(ROOT, "backend"), stdio: ["ignore", "pipe", "pipe"] }
  );
  py.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  py.stderr.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  py.on("exit", (code) => {
    console.log(`[backend] exited with code ${code}`);
    killAll(code ?? 1);
  });
  children.push(py);
  console.log("[vxdesk] backend  → http://127.0.0.1:8765");
}

function startFrontend() {
  const viteBin = path.join(
    FRONTEND,
    "node_modules",
    "vite",
    "bin",
    "vite.js"
  );
  if (!fs.existsSync(viteBin)) {
    console.error(
      "[vxdesk] frontend deps missing — run `npm run setup` (or `npm --prefix frontend install`) first."
    );
    process.exit(1);
  }
  const vite = spawn(process.execPath, [viteBin, ...viteArgs], {
    cwd: FRONTEND,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env },
  });
  vite.stdout.on("data", (d) => process.stdout.write(d));
  vite.stderr.on("data", (d) => process.stdout.write(d));
  vite.on("exit", (code) => {
    console.log(`[frontend] exited with code ${code}`);
    killAll(code ?? 1);
  });
  children.push(vite);
}

startBackend();
if (!backendOnly) startFrontend();
