"""`make doctor`: tools, versions, configuration, cache permissions and provider status. No secrets printed."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def ver(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        return "not found"


def main() -> int:
    ok = True
    print("== Tools")
    print(f"  python   {sys.version.split()[0]} ({sys.executable})")
    for name, cmd in [("uv", ["uv", "--version"]), ("node", ["node", "--version"]), ("npm", ["npm", "--version"]),
                      ("docker", ["docker", "--version"]), ("git", ["git", "--version"])]:
        print(f"  {name:<8} {ver(cmd) if shutil.which(cmd[0]) else 'not found'}")
    if sys.version_info[:2] != (3, 12):
        print("  ! tested with Python 3.12")
    print("== Python packages")
    from app.manifest import dependency_versions
    for k, v in dependency_versions().items():
        print(f"  {k:<12} {v}")
    print("== Configuration")
    from app.config import CACHE_DIR, RUNTIME_DIR, load_default_params, load_display_policy
    p = load_default_params()
    print(f"  research params {p.config_version} hash {p.hash()}")
    pol = load_display_policy()
    print(f"  display route {pol['active_route']}; public_display_permitted={pol['public_display_permitted']}")
    print(f"  PDE_SOURCE={os.environ.get('PDE_SOURCE', 'synthetic')}")
    secret_like = [k for k in os.environ if any(s in k.upper() for s in ("TOKEN", "SECRET", "KEY", "PASSWORD"))]
    print(f"  secret-like env vars present: {len(secret_like)} (values not shown)")
    print("== Writable paths")
    for d in (RUNTIME_DIR, CACHE_DIR, ROOT / "data" / "provider_snapshots"):
        try:
            d.mkdir(parents=True, exist_ok=True)
            t = d / ".write_test"
            t.write_text("x")
            t.unlink()
            print(f"  ok  {d}")
        except OSError as exc:
            ok = False
            print(f"  ERR {d}: {exc}")
    print("== Providers")
    from app.providers.synthetic import SyntheticProvider
    h = SyntheticProvider().health()
    print(f"  synthetic: {h['status']} rows={h.get('rows')} mode={h.get('mode')}")
    ok &= h["status"] == "ok"
    snap_log = ROOT / "data" / "provider_snapshots" / "refresh_log.jsonl"
    if snap_log.exists():
        last = json.loads(snap_log.read_text().strip().splitlines()[-1])
        print(f"  nse_mcp: last refresh {last.get('at')} -> {last.get('outcome')}")
    else:
        print("  nse_mcp: never refreshed (run `make refresh`)")
    dist = ROOT / "frontend" / "dist" / "index.html"
    print(f"== Frontend build: {'present' if dist.exists() else 'missing (make build)'}")
    print("\nDOCTOR:", "OK" if ok else "PROBLEMS FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
