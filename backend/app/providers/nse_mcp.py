"""NseMcpProvider: bounded, schema-checked access to NSE's documented MCP endpoints.

Rules implemented here (build kit section D):
* discover tools and store a snapshot BEFORE building any request;
* request arguments come from config/nse_mapping.yaml and must exist in the discovered schema;
* serial requests with conservative pacing, bounded exponential retries for transient
  failures only; permission/policy failures and malformed responses are never retried;
* cancellation via a threading.Event;
* data obtained here is REAL_UNVALIDATED; technical access never sets public-display permission;
* the provider never substitutes synthetic prices on failure.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

import pandas as pd

from ..config import SNAPSHOT_DIR, load_nse_mapping
from ..validation.validate import REAL_UNVALIDATED
from .base import (
    Dataset, Provider, ProviderError, ProviderNotConfigured, ProviderPermissionError,
    ProviderSchemaError, ProviderTransientError,
)

log = logging.getLogger("pde.nse_mcp")


class McpTransport(Protocol):
    async def list_tools(self, url: str, timeout: float) -> list[dict[str, Any]]: ...
    async def call_tool(self, url: str, name: str, arguments: dict[str, Any], timeout: float) -> Any: ...


def classify_exception(exc: BaseException) -> ProviderError:
    """Map low-level failures to retryable vs non-retryable provider errors."""
    if isinstance(exc, ProviderError):
        return exc
    text = f"{type(exc).__name__}: {exc}"
    try:
        import httpx
        if isinstance(exc, httpx.TimeoutException):
            return ProviderTransientError(f"timeout: {text}")
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in (401, 403, 407, 451):
                return ProviderPermissionError(f"HTTP {code}: permission/policy denial")
            if code == 429 or code >= 500:
                return ProviderTransientError(f"HTTP {code}")
            return ProviderError(f"HTTP {code}")
        if isinstance(exc, httpx.ProxyError):
            if "403" in str(exc) or "407" in str(exc):
                return ProviderPermissionError(f"proxy denied the connection (egress policy): {text}")
            return ProviderTransientError(f"proxy error: {text}")
        if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)):
            if "403" in str(exc):
                return ProviderPermissionError(f"connection refused with 403: {text}")
            return ProviderTransientError(f"connection error: {text}")
    except ImportError:  # pragma: no cover
        pass
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return ProviderTransientError(f"timeout: {text}")
    if isinstance(exc, PermissionError):
        return ProviderPermissionError(text)
    if isinstance(exc, (ConnectionError, OSError)):
        if "403" in str(exc):
            return ProviderPermissionError(text)
        return ProviderTransientError(text)
    # Exception groups from anyio task groups: classify the first leaf.
    inner = getattr(exc, "exceptions", None)
    if inner:
        return classify_exception(inner[0])
    if "403" in text or "Forbidden" in text:
        return ProviderPermissionError(text)
    return ProviderError(text)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0
    pacing_seconds: float = 2.0


class SdkTransport:
    """Real transport using the official MCP Python SDK (streamable HTTP)."""

    async def _session(self, url: str, timeout: float, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def run() -> Any:
            async with streamable_http_client(url) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                    await session.initialize()
                    return await fn(session)

        return await asyncio.wait_for(run(), timeout=timeout * 2)

    async def list_tools(self, url: str, timeout: float) -> list[dict[str, Any]]:
        async def fn(session: Any) -> list[dict[str, Any]]:
            tools: list[dict[str, Any]] = []
            cursor = None
            for _ in range(20):  # bounded pagination
                from mcp import types
                res = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
                for t in res.tools:
                    tools.append({"name": t.name, "description": t.description,
                                  "inputSchema": t.inputSchema,
                                  "outputSchema": getattr(t, "outputSchema", None)})
                cursor = getattr(res, "nextCursor", None)
                if not cursor:
                    break
            return tools
        return await self._session(url, timeout, fn)

    async def call_tool(self, url: str, name: str, arguments: dict[str, Any], timeout: float) -> Any:
        async def fn(session: Any) -> Any:
            res = await session.call_tool(name, arguments)
            if getattr(res, "isError", False):
                raise ProviderError(f"tool {name} returned an error result")
            structured = getattr(res, "structuredContent", None)
            if structured is not None:
                return structured
            texts = [c.text for c in getattr(res, "content", []) if getattr(c, "type", None) == "text"]
            return {"text": texts}
        return await self._session(url, timeout, fn)


def schema_hash(tools: list[dict[str, Any]]) -> str:
    canon = json.dumps(sorted(tools, key=lambda t: t["name"]), sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


class NseMcpProvider(Provider):
    name = "nse_mcp"
    mode = REAL_UNVALIDATED

    def __init__(self, transport: McpTransport | None = None, mapping: dict | None = None,
                 snapshot_dir: Path = SNAPSHOT_DIR, sleep: Callable[[float], None] = time.sleep,
                 cancel: threading.Event | None = None):
        self.transport = transport or SdkTransport()
        self.mapping = mapping if mapping is not None else load_nse_mapping()
        self.snapshot_dir = Path(snapshot_dir)
        self.sleep = sleep
        self.cancel = cancel or threading.Event()
        self.policy = RetryPolicy(max_attempts=int(self.mapping.get("max_attempts", 3)),
                                  pacing_seconds=float(self.mapping.get("pacing_seconds", 2.0)))
        self.timeout = float(self.mapping.get("timeout_seconds", 20))
        self._last_request = 0.0
        self.attempt_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ plumbing
    def _run(self, coro_factory: Callable[[], Awaitable[Any]], label: str) -> Any:
        last: ProviderError | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            if self.cancel.is_set():
                raise ProviderError("cancelled")
            wait = self.policy.pacing_seconds - (time.monotonic() - self._last_request)
            if self._last_request and wait > 0:
                self.sleep(wait)
            self._last_request = time.monotonic()
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                result = asyncio.run(coro_factory())
                self.attempt_log.append({"op": label, "attempt": attempt, "at": started, "outcome": "ok"})
                return result
            except BaseException as exc:  # noqa: BLE001 - classified below
                if isinstance(exc, KeyboardInterrupt):
                    raise
                err = classify_exception(exc)
                self.attempt_log.append({"op": label, "attempt": attempt, "at": started,
                                         "outcome": type(err).__name__, "detail": str(err)[:300]})
                if not isinstance(err, ProviderTransientError):
                    raise err from None
                last = err
                if attempt < self.policy.max_attempts:
                    self.sleep(min(self.policy.base_delay * 2 ** (attempt - 1), self.policy.max_delay))
        assert last is not None
        raise last

    def endpoints(self) -> dict[str, str]:
        return dict(self.mapping.get("endpoints", {}))

    # ------------------------------------------------------------------ discovery
    def discover(self, endpoint_key: str) -> dict[str, Any]:
        url = self.endpoints()[endpoint_key]
        tools = self._run(lambda: self.transport.list_tools(url, self.timeout), f"list_tools:{endpoint_key}")
        if not isinstance(tools, list) or not all(isinstance(t, dict) and "name" in t for t in tools):
            raise ProviderSchemaError("malformed tools/list response")
        snap = {
            "endpoint_key": endpoint_key, "url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_tools": len(tools), "schema_sha256": schema_hash(tools), "tools": tools,
        }
        path = self.snapshot_dir / f"nse_{endpoint_key}_tools.json"
        previous = None
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8")).get("schema_sha256")
            except json.JSONDecodeError:
                previous = None
        snap["schema_changed_since_last_snapshot"] = bool(previous and previous != snap["schema_sha256"])
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snap, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return snap

    def load_snapshot(self, endpoint_key: str) -> dict[str, Any] | None:
        p = self.snapshot_dir / f"nse_{endpoint_key}_tools.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def validate_mapping(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        tool_name = self.mapping.get("history_tool")
        args = self.mapping.get("arguments") or {}
        if not tool_name or not args:
            raise ProviderNotConfigured(
                "history_tool/arguments are not configured; inspect the discovery snapshot and fill "
                "config/nse_mapping.yaml (argument names must come from the discovered schema)")
        tools = {t["name"]: t for t in snapshot.get("tools", [])}
        if tool_name not in tools:
            raise ProviderSchemaError(f"configured tool {tool_name!r} not present in discovered tools")
        schema = tools[tool_name].get("inputSchema") or {}
        props = set((schema.get("properties") or {}).keys())
        required = set(schema.get("required") or [])
        unknown = set(args) - props
        if unknown:
            raise ProviderSchemaError(f"mapped arguments not in discovered schema: {sorted(unknown)}")
        missing = required - set(args)
        if missing:
            raise ProviderSchemaError(f"discovered schema requires unmapped arguments: {sorted(missing)}")
        return tools[tool_name]

    # ------------------------------------------------------------------ history
    def fetch_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        endpoint_key = self.mapping.get("history_endpoint")
        if not endpoint_key:
            raise ProviderNotConfigured("history_endpoint not configured")
        snap = self.load_snapshot(endpoint_key)
        if snap is None:
            raise ProviderNotConfigured("no discovery snapshot; run discovery before requesting history")
        self.validate_mapping(snap)
        url = self.endpoints()[endpoint_key]
        values = {"symbol": symbol, "start": start, "end": end, "date": end}
        args = {k: (v.format(**values) if isinstance(v, str) else v) for k, v in self.mapping["arguments"].items()}
        raw = self._run(lambda: self.transport.call_tool(url, self.mapping["history_tool"], args, self.timeout),
                        f"call_tool:{symbol}")
        return self.parse_history(raw, symbol)

    def parse_history(self, raw: Any, symbol: str) -> pd.DataFrame:
        fields = self.mapping.get("response_fields") or {}
        needed = ["date", "open", "high", "low", "close", "volume"]
        if any(f not in fields for f in needed):
            raise ProviderNotConfigured("response_fields mapping incomplete")
        records = raw
        if isinstance(raw, dict) and "text" in raw:
            try:
                records = [json.loads(t) for t in raw["text"]]
                records = records[0] if len(records) == 1 else records
            except (json.JSONDecodeError, TypeError) as exc:
                raise ProviderSchemaError(f"malformed tool response: {exc}") from None
        if isinstance(records, dict):
            lists = [v for v in records.values() if isinstance(v, list)]
            records = lists[0] if len(lists) == 1 else None
        if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
            raise ProviderSchemaError("malformed tool response: expected a non-empty list of records")
        rows = []
        for r in records:
            try:
                rows.append({
                    "symbol": symbol, "exchange": "NSE", "series": self.mapping.get("series", "EQ"),
                    "date": pd.Timestamp(r[fields["date"]]).strftime("%Y-%m-%d"),
                    "open": float(r[fields["open"]]), "high": float(r[fields["high"]]),
                    "low": float(r[fields["low"]]), "close": float(r[fields["close"]]),
                    "volume": int(float(r[fields["volume"]])),
                    "provider": "nse_mcp", "adjustment_status": "unknown",
                    "dataset_id": f"nse_mcp_{datetime.now(timezone.utc):%Y%m%d}",
                })
            except (KeyError, ValueError, TypeError) as exc:
                raise ProviderSchemaError(f"malformed record: {exc}") from None
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ Provider API
    def symbols(self) -> list[str]:
        from ..config import load_universe
        uni = load_universe("universe_nse_candidates.yaml")
        return sorted({s for g in uni["groups"].values() for s in g})

    def history(self, symbol: str) -> pd.DataFrame:
        raise ProviderNotConfigured("use fetch_history(symbol, start, end) after discovery and mapping")

    def metadata(self) -> dict[str, Any]:
        return {"provider": self.name, "endpoints": self.endpoints(), "mode": REAL_UNVALIDATED,
                "public_display_permitted": False,
                "usage_note": "NSE MCP documentation limits use to informational purposes and excludes "
                              "commercial deployment; see DATA_RIGHTS.md"}

    def health(self) -> dict[str, Any]:
        """Redacted health: no headers, tokens or response bodies are recorded."""
        out: dict[str, Any] = {"provider": self.name, "checked_at":
                               datetime.now(timezone.utc).isoformat(timespec="seconds"), "endpoints": {}}
        for key in self.endpoints():
            try:
                snap = self.discover(key)
                out["endpoints"][key] = {"status": "reachable", "n_tools": snap["n_tools"],
                                         "schema_sha256": snap["schema_sha256"]}
            except ProviderError as exc:
                out["endpoints"][key] = {"status": "unavailable", "error_class": type(exc).__name__,
                                         "detail": str(exc)[:240]}
        out["status"] = "ok" if all(e["status"] == "reachable" for e in out["endpoints"].values()) else "degraded"
        out["attempts"] = self.attempt_log
        out["public_display_permitted"] = False
        return out

    def freshness(self) -> dict[str, Any]:
        return {"note": "no NSE data has been retrieved in this environment"}

    def load_dataset(self) -> Dataset:
        raise ProviderNotConfigured("NSE history is not available; see REAL_DATA_READINESS.md")
