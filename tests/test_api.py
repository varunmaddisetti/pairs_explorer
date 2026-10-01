"""API behaviour: labels, honest zero-result state, useful errors, experiment logging."""
import pytest
from fastapi.testclient import TestClient

from app.api import main as api

ZERO_DATE = "2023-02-07"  # fold-4 formation end: no pair passes BY-FDR (verified honest zero state)


@pytest.fixture(scope="module")
def client():
    api.reset_state()
    return TestClient(api.app)


def test_status_labels(client):
    s = client.get("/api/status").json()
    assert s["mode"] == "SYNTHETIC_DEMO" and s["statuses"]["SYNTHETIC_DEMO"] is True
    assert s["statuses"]["PUBLIC_DISPLAY_PERMITTED"] is False and s["statuses"]["REAL_RESEARCH_VALIDATED"] is False
    assert s["calendar"] == "weekdays_only_not_nse_calendar"


def test_scanner_shape_and_honest_zero_results(client):
    s = client.get("/api/scanner", params={"as_of": "2022-12-30"}).json()
    assert s["family"]["family_size"] + s["family"]["n_skipped"] == 4
    assert len(s["eligible"]) + len(s["excluded"]) == 4
    for r in s["excluded"]:
        assert r["exclusion_reasons"]
    zs = [abs(r["z_last"]) for r in s["eligible"]]
    assert zs == sorted(zs, reverse=True)
    # a date where nothing passes BY-FDR: the API returns an empty eligible list, not fillers
    empty = client.get("/api/scanner", params={"as_of": ZERO_DATE}).json()
    assert empty["eligible"] == [] and empty["family"]["n_eligible"] == 0
    assert len(empty["excluded"]) == 4 and all(r["exclusion_reasons"] for r in empty["excluded"])


def test_errors_are_useful(client):
    assert client.get("/api/pair", params={"a": "S_BANK_A", "b": "S_IT_A"}).status_code == 404
    assert client.get("/api/scanner", params={"as_of": "1990-01-01"}).status_code == 400
    r = client.post("/api/backtest", json={"a": "S_BANK_A", "b": "S_BANK_B", "params": {"fdr_alpha": 0.5}})
    assert r.status_code == 400 and "not editable" in r.text
    r = client.post("/api/backtest", json={"a": "S_BANK_A", "b": "S_BANK_B", "params": {"entry_z": 0.2}})
    assert r.status_code == 422


def test_exploratory_runs_logged(client):
    before = client.get("/api/experiments").json()
    r = client.post("/api/backtest", json={"a": "S_BANK_A", "b": "S_BANK_B", "params": {"slippage_bps": 30}}).json()
    assert r["experiment_class"].startswith("exploratory")
    after = client.get("/api/experiments").json()
    assert after["total_runs"] == before["total_runs"] + 1
    assert after["exploratory_runs"] == before["exploratory_runs"] + 1
    assert after["runs_touching_holdout"] >= 1


def test_card_png_and_synthetic_label(client):
    r = client.get("/api/card.png", params={"a": "S_BANK_A", "b": "S_BANK_B", "as_of": "2023-06-30"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "synthetic_demo" in r.headers["content-disposition"]


def test_csv_injection_guard():
    assert api._safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert api._safe_cell(-3.2) == -3.2
