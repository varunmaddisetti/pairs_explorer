"""Portable one-command launcher (used by `make demo`, start_demo.sh and start_demo.ps1).

* synthetic mode by default, no keys, binds to 127.0.0.1;
* builds the frontend once if no production build exists (needs Node);
* picks the first free port from --port upward and prints the actual URL;
* cleans up child processes on Ctrl+C / SIGTERM.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist" / "index.html"


def free_port(host: str, start: int, tries: int = 50) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"no free port in {start}-{start + tries - 1}")


def npm() -> str | None:
    return shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")


def newest_source_mtime() -> float:
    files = list((FRONTEND / "src").rglob("*")) + [FRONTEND / "index.html", FRONTEND / "package-lock.json"]
    return max(f.stat().st_mtime for f in files if f.is_file())


def ensure_build(force: bool) -> None:
    stale = DIST.exists() and newest_source_mtime() > DIST.stat().st_mtime
    if DIST.exists() and not force and not stale:
        return
    n = npm()
    if n is None:
        if DIST.exists():
            print("! npm not found; serving the existing (possibly stale) frontend build")
            return
        raise SystemExit("Node.js/npm is required to build the frontend once (see README).")
    if not (FRONTEND / "node_modules").exists():
        print("> installing frontend dependencies (npm ci)")
        subprocess.run([n, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    print("> building frontend")
    subprocess.run([n, "run", "build"], cwd=FRONTEND, check=True)


def wait_health(url: str, proc: subprocess.Popen, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise SystemExit(f"backend exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.4)
    raise SystemExit("backend did not become healthy in time")


def main() -> None:
    ap = argparse.ArgumentParser(description="Start Pairs Divergence Explorer locally")
    ap.add_argument("--host", default=os.environ.get("PDE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PDE_PORT", "8000")))
    ap.add_argument("--dev", action="store_true", help="also run the Vite dev server with hot reload")
    ap.add_argument("--rebuild", action="store_true", help="force a frontend production build")
    ap.add_argument("--check", action="store_true", help="start, verify health and key endpoints, then exit")
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"! binding to {args.host}: the app will be reachable from other machines. Local/private is the default.")

    env = os.environ.copy()
    env.setdefault("PDE_SOURCE", "synthetic")
    env["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + env.get("PYTHONPATH", "")
    if not args.dev:
        ensure_build(args.rebuild)
    port = free_port(args.host, args.port)
    if port != args.port:
        print(f"! port {args.port} is busy; using {port}")
    procs: list[subprocess.Popen] = []
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", args.host,
                                "--port", str(port), "--log-level", "warning"], cwd=ROOT / "backend", env=env)
    procs.append(backend)

    def shutdown(*_: object) -> None:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    base = f"http://{args.host}:{port}"
    wait_health(base, backend)
    if args.check:
        for path in ("/api/status", "/api/scanner", "/"):
            with urllib.request.urlopen(base + path, timeout=30) as r:
                print(f"  {path} -> {r.status}")
        print(f"OK: one-command start verified at {base}")
        shutdown()
    url = base
    if args.dev:
        n = npm()
        if n is None:
            raise SystemExit("npm is required for --dev")
        vport = free_port(args.host, 5173)
        venv = env | {"PDE_API_URL": base}
        procs.append(subprocess.Popen([n, "run", "dev", "--", "--port", str(vport), "--strictPort"], cwd=FRONTEND, env=venv))
        url = f"http://{args.host}:{vport}"
    print("\n  Pairs Divergence Explorer (SYNTHETIC DEMO, local/private)")
    print(f"  Open: {url}\n  API docs: {base}/api/docs\n  Press Ctrl+C to stop.\n", flush=True)
    while True:
        for p in procs:
            if p.poll() is not None:
                print(f"! a child process exited with code {p.returncode}; shutting down")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()
