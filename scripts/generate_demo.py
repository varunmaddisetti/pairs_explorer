"""Regenerate the canonical synthetic demo dataset into data/demo/."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data.canonical_generator import generate_demo  # noqa: E402

if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "demo"
    manifest = generate_demo(dest)
    print(json.dumps({k: manifest[k] for k in ("dataset_id", "rows", "csv_sha256")}, indent=2))
