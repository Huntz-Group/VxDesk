#!/usr/bin/env node
/**
 * One-time setup: create the backend venv, install Python deps, install
 * frontend npm deps. Safe to re-run (idempotent-ish).
 */
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const FRONTEND = path.join(ROOT, "frontend");
const VENV_PY = path.join(BACKEND, ".venv", "Scripts", "python.exe");

function run(cmd, args, cwd) {
  console.log(`\n> ${cmd} ${args.join(" ")}  (in ${cwd})`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: false });
  if (r.status !== 0) {
    console.error(`setup step failed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
}

if (!fs.existsSync(VENV_PY)) {
  run("python", ["-m", "venv", ".venv"], BACKEND);
} else {
  console.log("backend venv already exists, skipping creation");
}

run(VENV_PY, ["-m", "pip", "install", "-r", "requirements.txt"], BACKEND);
// onnxruntime-directml conflicts with the plain onnxruntime wheel that
// rapidocr-onnxruntime pulls in; replace it so OCR can use the GPU (DirectML).
run(VENV_PY, ["-m", "pip", "uninstall", "-y", "onnxruntime"], BACKEND);
run(VENV_PY, ["-m", "pip", "install", "onnxruntime-directml"], BACKEND);

const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
run(npmCmd, ["install"], FRONTEND);

console.log("\nSetup complete. Start everything with:  npm run dev");
