"""Gate J9: provider contracts (NSE MCP adapter with mocked transport; FileProvider safety)."""
import asyncio
import json

import httpx
import pandas as pd
import pytest

from app.config import file_sha256
from app.providers.base import (ProviderError, ProviderNotConfigured, ProviderPermissionError,
                                ProviderSchemaError, ProviderTransientError)
from app.providers.file import FileProvider
from app.providers.nse_mcp import NseMcpProvider, classify_exception

TOOLS = [{"name": "get_history", "description": "x",
          "inputSchema": {"type": "object", "properties": {"symbol": {}, "from_date": {}, "to_date": {}},
                          "required": ["symbol", "from_date", "to_date"]}}]
MAPPING = {"endpoints": {"bhavcopy_cm": "https://example.invalid/mcp"}, "history_endpoint": "bhavcopy_cm",
           "history_tool": "get_history", "arguments": {"symbol": "{symbol}", "from_date": "{start}", "to_date": "{end}"},
           "response_fields": {"date": "D", "open": "O", "high": "H", "low": "L", "close": "C", "volume": "V"},
           "pacing_seconds": 0.0, "max_attempts": 3, "timeout_seconds": 1}


class Fake:
    def __init__(self, tools=TOOLS, list_exc=None, call_result=None, call_exc=None):
        self.tools, self.list_exc, self.call_result, self.call_exc = tools, list_exc, call_result, call_exc
        self.list_calls = self.call_calls = 0

    async def list_tools(self, url, timeout):
        self.list_calls += 1
        if self.list_exc:
            raise self.list_exc
        return self.tools

    async def call_tool(self, url, name, arguments, timeout):
        self.call_calls += 1
        self.last_args = arguments
        if self.call_exc:
            raise self.call_exc
        return self.call_result


def provider(tmp_path, fake, mapping=MAPPING):
    sleeps = []
    p = NseMcpProvider(transport=fake, mapping=dict(mapping), snapshot_dir=tmp_path, sleep=sleeps.append)
    return p, sleeps


def test_discovery_snapshot_and_mapping_validation(tmp_path):
    p, _ = provider(tmp_path, Fake())
    snap = p.discover("bhavcopy_cm")
    assert snap["n_tools"] == 1 and (tmp_path / "nse_bhavcopy_cm_tools.json").exists()
    assert p.validate_mapping(snap)["name"] == "get_history"


def test_schema_change_detected_and_blocks_requests(tmp_path):
    p, _ = provider(tmp_path, Fake())
    p.discover("bhavcopy_cm")
    renamed = json.loads(json.dumps(TOOLS))
    renamed[0]["inputSchema"]["properties"] = {"symbol": {}, "start": {}, "end": {}}
    renamed[0]["inputSchema"]["required"] = ["symbol", "start", "end"]
    p2, _ = provider(tmp_path, Fake(tools=renamed))
    snap = p2.discover("bhavcopy_cm")
    assert snap["schema_changed_since_last_snapshot"] is True
    with pytest.raises(ProviderSchemaError, match="not in discovered schema"):
        p2.fetch_history("AAA", "2025-01-01", "2025-02-01")


def test_timeout_is_retried_with_bounded_backoff(tmp_path):
    fake = Fake(list_exc=httpx.ReadTimeout("slow"))
    p, sleeps = provider(tmp_path, fake)
    with pytest.raises(ProviderTransientError):
        p.discover("bhavcopy_cm")
    assert fake.list_calls == 3                      # bounded: max_attempts
    assert sleeps == [1.0, 2.0]                      # exponential backoff between attempts, no infinite loop


def test_permission_error_not_retried(tmp_path):
    req = httpx.Request("POST", "https://example.invalid/mcp")
    exc = httpx.HTTPStatusError("forbidden", request=req, response=httpx.Response(403, request=req))
    fake = Fake(list_exc=exc)
    p, sleeps = provider(tmp_path, fake)
    with pytest.raises(ProviderPermissionError):
        p.discover("bhavcopy_cm")
    assert fake.list_calls == 1 and sleeps == []


def test_proxy_denial_classified_as_permission():
    assert isinstance(classify_exception(httpx.ProxyError("403 Forbidden")), ProviderPermissionError)
    assert isinstance(classify_exception(asyncio.TimeoutError()), ProviderTransientError)


def test_malformed_responses(tmp_path):
    p, _ = provider(tmp_path, Fake(tools=[{"no_name": 1}]))
    with pytest.raises(ProviderSchemaError):
        p.discover("bhavcopy_cm")
    fake = Fake(call_result={"text": ["not json"]})
    p, _ = provider(tmp_path, fake)
    p.discover("bhavcopy_cm")
    with pytest.raises(ProviderSchemaError, match="malformed"):
        p.fetch_history("AAA", "2025-01-01", "2025-02-01")
    assert fake.call_calls == 1                       # malformed data is not retried
    fake2 = Fake(call_result=[{"D": "2025-01-02", "O": "x"}])
    p, _ = provider(tmp_path, fake2)
    with pytest.raises(ProviderSchemaError):
        p.fetch_history("AAA", "2025-01-01", "2025-02-01")


def test_good_response_is_real_unvalidated_unknown_adjustment(tmp_path):
    rec = [{"D": "2025-01-02", "O": 10, "H": 11, "L": 9, "C": 10.5, "V": 100}]
    fake = Fake(call_result=rec)
    p, _ = provider(tmp_path, fake)
    p.discover("bhavcopy_cm")
    df = p.fetch_history("AAA", "2025-01-01", "2025-02-01")
    assert fake.last_args == {"symbol": "AAA", "from_date": "2025-01-01", "to_date": "2025-02-01"}
    assert df["adjustment_status"].tolist() == ["unknown"] and df["provider"].tolist() == ["nse_mcp"]
    assert p.mode == "REAL_UNVALIDATED"
    h = p.health()
    assert h["status"] == "ok" and h["public_display_permitted"] is False


def test_unconfigured_mapping_and_no_synthetic_substitution(tmp_path):
    p, _ = provider(tmp_path, Fake(), mapping={**MAPPING, "history_tool": None, "arguments": {}})
    p.discover("bhavcopy_cm")
    with pytest.raises(ProviderNotConfigured):
        p.fetch_history("AAA", "2025-01-01", "2025-02-01")
    with pytest.raises(ProviderNotConfigured):
        p.load_dataset()                               # never falls back to synthetic prices


def test_cancellation(tmp_path):
    p, _ = provider(tmp_path, Fake())
    p.cancel.set()
    with pytest.raises(ProviderError, match="cancelled"):
        p.discover("bhavcopy_cm")


# ------------------------------------------------------------------ FileProvider
def _write_import(root, name, frame, **overrides):
    d = root / name
    d.mkdir(parents=True)
    frame.to_csv(d / "data.csv", index=False)
    m = {"dataset_id": "u1", "source": "user", "retrieved_at": "2026-09-01T00:00:00Z", "timezone": "Asia/Kolkata",
         "price_basis": "total_return_adjusted", "corporate_actions": "vendor adjusted", "permitted_usage": "private",
         "retention": "local", "identity_verified": True, "corporate_actions_accounted": True,
         "data_sha256": file_sha256(d / "data.csv"), "universe_version": "u1", "groups": {"G": ["AAA", "BBB"]},
         "validation_status": "REAL_RESEARCH_VALIDATED"} | overrides
    (d / "manifest.json").write_text(json.dumps(m))
    return d


def test_file_provider_path_safety(tmp_path):
    for bad in ("../etc", "a/b", "", "..", "/abs"):
        with pytest.raises(ProviderError):
            FileProvider(bad, import_root=tmp_path)


def test_file_provider_promotion_and_hash(tmp_path):
    from test_validation import real_frame
    _write_import(tmp_path, "good", real_frame())
    assert FileProvider("good", tmp_path).load_dataset().mode == "REAL_RESEARCH_VALIDATED"
    _write_import(tmp_path, "unverified", real_frame(), identity_verified=False)
    assert FileProvider("unverified", tmp_path).load_dataset().mode == "REAL_UNVALIDATED"
    f = real_frame(); f["adjustment_status"] = "unknown"
    _write_import(tmp_path, "unknownadj", f)
    assert FileProvider("unknownadj", tmp_path).load_dataset().mode == "REAL_UNVALIDATED"
    d = _write_import(tmp_path, "tampered", real_frame())
    (d / "data.csv").write_text((d / "data.csv").read_text() + "\n")
    with pytest.raises(Exception, match="hash"):
        FileProvider("tampered", tmp_path).load_dataset()
    syn = real_frame(); syn["exchange"] = "SYNTHETIC"
    _write_import(tmp_path, "fake_real", syn)
    with pytest.raises(Exception, match="synthetic"):
        FileProvider("fake_real", tmp_path).load_dataset()
