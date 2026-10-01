import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
_tmp = tempfile.mkdtemp(prefix="pde_test_")
os.environ.setdefault("PDE_RUNTIME_DIR", str(Path(_tmp) / "runtime"))
os.environ.setdefault("PDE_CACHE_DIR", str(Path(_tmp) / "cache"))
os.environ["PDE_WARM"] = "0"

from app.backtest.engine import Costs, FoldSpec  # noqa: E402
from app.config import ResearchParams, load_default_params  # noqa: E402
from app.providers.synthetic import SyntheticProvider  # noqa: E402


@pytest.fixture(scope="session")
def ds():
    return SyntheticProvider().load_dataset()


@pytest.fixture(scope="session")
def params() -> ResearchParams:
    return load_default_params()


ZERO = Costs(0, 0, 0, 0, "simple_debit")


class Toy:
    """Hand-built single-fold market for engine oracles. Index 0 is the last formation close."""

    def __init__(self, n=40, a=100.0, b=200.0):
        self.dates = pd.bdate_range("2024-01-01", periods=n)
        self.oa = np.full(n, a); self.ca = np.full(n, a)
        self.ob = np.full(n, b); self.cb = np.full(n, b)
        self.z = np.full(n, 0.0)

    def fold(self, eval_end=None, beta=1.0, tradable=True, k=0):
        n = len(self.dates)
        return FoldSpec(k, 0, 1, eval_end if eval_end is not None else n - 1, "development", tradable, beta, self.z)

    def run(self, p=None, costs=ZERO, folds=None):
        from app.backtest.engine import simulate_sleeve
        p = p or load_default_params()
        return simulate_sleeve(self.dates, self.oa, self.ca, self.ob, self.cb, folds or [self.fold()], p, costs,
                               "A", "B")


@pytest.fixture
def toy():
    return Toy()
