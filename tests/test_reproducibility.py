"""Gate J10: canonical generator and frozen runs reproduce identical hashes."""
import json

from app.backtest.run import run_pair_backtest
from app.config import DEMO_DIR, file_sha256
from app.data.canonical_generator import generate_demo
from app.manifest import stable_hash, strip_volatile


def test_generator_reproduces_committed_fixture(tmp_path):
    committed = json.loads((DEMO_DIR / "canonical_demo_manifest.json").read_text())
    m1 = generate_demo(tmp_path / "a")
    m2 = generate_demo(tmp_path / "b")
    assert m1["csv_sha256"] == m2["csv_sha256"] == committed["csv_sha256"] == file_sha256(DEMO_DIR / "canonical_demo.csv")
    assert m1["rows"] == 10080 and m1["sessions"] == 1260


def test_repeated_runs_identical(ds, params):
    r1 = run_pair_backtest(ds, "S_BANK_A", "S_BANK_B", params)
    r2 = run_pair_backtest(ds, "S_BANK_A", "S_BANK_B", params)
    assert r1["result_sha256"] == r2["result_sha256"]
    assert stable_hash(strip_volatile(r1["manifest"])) == stable_hash(strip_volatile(r2["manifest"]))
    m = r1["manifest"]
    for k in ("dataset_content_sha256", "universe_version", "observation_cutoff", "config_version", "params",
              "source_mode", "dependency_versions", "seed", "run_time"):
        assert k in m
    assert "key" not in json.dumps(m).lower() or "api_key" not in json.dumps(m).lower()
