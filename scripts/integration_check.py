"""VxDesk live integration check — run while `npm run dev` is up.

Verifies: backend /api/system/info, node catalog, Vite proxy, workflow CRUD,
validation, a full sample-workflow run, run history, screenshot endpoint.
Prints a PASS/FAIL summary; exits non-zero on any failure.
"""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "http://127.0.0.1:8765"
FRONTEND = "http://localhost:7100"

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((name, True, detail or ""))
        print(f"PASS  {name}  {detail or ''}")
    except Exception as e:  # noqa: BLE001
        results.append((name, False, str(e)))
        print(f"FAIL  {name}  -> {e}")


def sysinfo():
    r = httpx.get(f"{BACKEND}/api/system/info", timeout=10)
    r.raise_for_status()
    d = r.json()
    assert d["capture"]["backend"] in ("dxcam", "mss", "file"), d
    return f"capture={d['capture']['backend']} ocr_gpu={d['ocr'].get('gpu')} gpu={d['gpu']['name']}"


def vite_proxy():
    r = httpx.get(f"{FRONTEND}/api/system/info", timeout=10)
    r.raise_for_status()
    return "vite -> backend proxy OK"


def vite_html():
    r = httpx.get(FRONTEND, timeout=10)
    r.raise_for_status()
    assert "<div id=\"root\">" in r.text or 'id="root"' in r.text
    return "index.html served"


def catalog():
    r = httpx.get(f"{BACKEND}/api/nodes/catalog", timeout=10)
    r.raise_for_status()
    n = len(r.json()["nodes"])
    assert n >= 18, n
    return f"{n} node types"


created_ids = []


def create_samples():
    for sample in sorted((ROOT / "scripts" / "samples").glob("*.json")):
        body = json.loads(sample.read_text(encoding="utf-8"))
        r = httpx.post(f"{BACKEND}/api/workflows",
                       json={"name": body["name"], "description": body.get("description", "")},
                       timeout=10)
        assert r.status_code in (200, 201), r.text
        wf = r.json()
        body["id"] = wf["id"]
        # keep the auto-created trigger node if present in the stored graph
        existing = {n["id"] for n in wf.get("nodes", [])}
        for n in body["nodes"]:
            existing.discard(n["id"])
        r2 = httpx.put(f"{BACKEND}/api/workflows/{wf['id']}", json=body, timeout=10)
        r2.raise_for_status()
        created_ids.append((wf["id"], body["name"]))
    return ", ".join(n for _, n in created_ids)


def validate_samples():
    for wf_id, name in created_ids:
        r = httpx.post(f"{BACKEND}/api/workflows/{wf_id}/validate", timeout=10)
        r.raise_for_status()
        d = r.json()
        assert d["valid"], f"{name}: {d['errors']}"
    return "all samples valid"


def run_welcome():
    wf_id = next(i for i, n in created_ids if n.startswith("Welcome"))
    r = httpx.post(f"{BACKEND}/api/workflows/{wf_id}/run", json={}, timeout=10)
    r.raise_for_status()
    run_id = r.json()["run_id"]
    for _ in range(60):
        time.sleep(0.5)
        d = httpx.get(f"{BACKEND}/api/runs/{run_id}", timeout=10).json()
        if d["status"] not in ("running", "pending", "queued"):
            break
    assert d["status"] == "success", json.dumps(d)[:800]
    shot = ROOT / "runs" / "welcome_shot.png"
    assert shot.exists() and shot.stat().st_size > 10_000, "screenshot not written"
    return f"run {run_id} success, screenshot {shot.stat().st_size//1024} KB"


def runs_history():
    wf_id = next(i for i, n in created_ids if n.startswith("Welcome"))
    r = httpx.get(f"{BACKEND}/api/workflows/{wf_id}/runs", timeout=10)
    r.raise_for_status()
    assert len(r.json()) >= 1
    return f"{len(r.json())} run(s) recorded"


def screenshot_endpoint():
    r = httpx.post(f"{BACKEND}/api/capture/screenshot", json={}, timeout=20)
    r.raise_for_status()
    assert r.headers["content-type"].startswith("image/")
    assert r.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff")
    return f"{len(r.content)//1024} KB image"


if __name__ == "__main__":
    check("system/info", sysinfo)
    check("vite proxy /api", vite_proxy)
    check("vite serves index", vite_html)
    check("node catalog", catalog)
    check("create sample workflows", create_samples)
    check("validate samples", validate_samples)
    check("run welcome workflow E2E", run_welcome)
    check("runs history", runs_history)
    check("screenshot endpoint", screenshot_endpoint)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)
