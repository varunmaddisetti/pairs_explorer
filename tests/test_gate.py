"""Gate J12: observation-age gate covers every route; display permission never follows from access."""
import io
import zipfile
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main as api
from app.gate import DisplayNotPermitted, DisplayPolicy
from app.providers.base import build_dataset

REF = "2025-06-30"
CUTOFF = "2025-05-16"   # REF - 45 calendar days


@pytest.fixture
def gated_client(monkeypatch):
    monkeypatch.setenv("PDE_DISPLAY_ROUTE", "public_educational")
    monkeypatch.setenv("PDE_REFERENCE_DATE", REF)
    api.reset_state()
    yield TestClient(api.app)
    api.reset_state()


def test_policy_cutoff():
    pol = DisplayPolicy.load("public_educational", date.fromisoformat(REF))
    assert pol.cutoff == pd.Timestamp(CUTOFF) and pol.public_display_permitted is False
    assert DisplayPolicy.load("local_research").cutoff is None


def test_every_route_respects_cutoff(gated_client):
    c = gated_client
    st = c.get("/api/status").json()
    assert st["last_date"] <= CUTOFF and st["display_policy"]["observation_cutoff"] == CUTOFF
    sc = c.get("/api/scanner").json()
    assert sc["as_of"] <= CUTOFF
    future = c.get("/api/scanner", params={"as_of": "2025-12-31"}).json()
    assert future["as_of"] <= CUTOFF                          # later request is clamped, not served
    d = c.get("/api/pair", params={"a": "S_BANK_A", "b": "S_BANK_B", "as_of": "2025-12-31"}).json()
    assert d["as_of"] <= CUTOFF and max(d["descriptive"]["dates"]) <= CUTOFF and d["available_until"] <= CUTOFF
    rv = c.get("/api/reveal", params={"a": "S_BANK_A", "b": "S_BANK_B", "as_of": "2025-04-30", "horizon": 252}).json()
    assert rv.get("dates") and max(rv["dates"]) <= CUTOFF and rv["sessions_available"] < 252
    bt = c.post("/api/backtest", json={"a": "S_BANK_A", "b": "S_BANK_B"}).json()
    assert max(x["date"] for x in bt["daily"]) <= CUTOFF and bt["manifest"]["observation_cutoff"] <= CUTOFF
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/backtest/{bt['run_id']}/bundle.zip").content))
    daily = pd.read_csv(z.open("daily_ledger.csv"))
    assert daily["date"].max() <= CUTOFF
    card = c.get("/api/card.png", params={"a": "S_BANK_A", "b": "S_BANK_B", "as_of": "2025-12-31"})
    assert card.status_code == 200 and "2025-12" not in card.headers["content-disposition"]
    assert card.headers["content-disposition"].split("_")[-3] <= CUTOFF


def test_real_data_not_displayable_on_public_route():
    from test_validation import real_frame
    ds = build_dataset(real_frame(), "REAL_UNVALIDATED", {}, {"G": ["AAA", "BBB"]}, "t")
    with pytest.raises(DisplayNotPermitted):
        DisplayPolicy.load("public_educational", date.fromisoformat(REF)).apply(ds)
    assert DisplayPolicy.load("local_research").apply(ds) is ds


def test_successful_access_does_not_grant_public_display(tmp_path):
    from test_providers import Fake, MAPPING
    from app.providers.nse_mcp import NseMcpProvider
    p = NseMcpProvider(transport=Fake(), mapping=dict(MAPPING), snapshot_dir=tmp_path, sleep=lambda s: None)
    assert p.health()["status"] == "ok"
    assert DisplayPolicy.load().public_display_permitted is False
    assert p.metadata()["public_display_permitted"] is False
