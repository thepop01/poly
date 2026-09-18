"""Polymarket v2 Data API adapter — envelope/cursor normalization."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Literal
import aiohttp

BASE_URL = "https://data-api.polymarket.com"
_BATCH = 20


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _b(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in {"true", "1", "yes"}
    return bool(val)


@dataclass
class PositionRow:
    proxy_wallet: str
    condition_id: str
    event_id: str | None
    status: str
    outcome_index: int | None
    source_total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    entry_cost_usdc: float
    total_cost_usdc: float
    entry_fees_usdc: float
    avg_price: float
    current_size: float
    total_size: float
    mergeable: bool
    raw: dict = field(repr=False)


def _parse_row(d: dict) -> PositionRow:
    outcome_index = d.get("outcomeIndex")
    if outcome_index is None:
        outcome_index = d.get("outcome_index")

    return PositionRow(
        proxy_wallet=str(d.get("proxyWallet") or d.get("proxy_wallet") or ""),
        condition_id=str(d.get("conditionId") or d.get("condition_id") or ""),
        event_id=d.get("eventId") or d.get("event_id"),
        status=str(d.get("status") or "OPEN").upper(),
        outcome_index=outcome_index,
        source_total_pnl=_f(d.get("totalPnl") or d.get("total_pnl")),
        realized_pnl=_f(d.get("realizedPnl") or d.get("realized_pnl")),
        unrealized_pnl=_f(d.get("unrealizedPnl") or d.get("unrealized_pnl")),
        entry_cost_usdc=_f(d.get("entryCostUsdc") or d.get("entry_cost_usdc")),
        total_cost_usdc=_f(d.get("totalCostUsdc") or d.get("total_cost_usdc")),
        entry_fees_usdc=_f(d.get("entryFeesUsdc") or d.get("entry_fees_usdc")),
        avg_price=_f(d.get("avgPrice") or d.get("avg_price")),
        current_size=_f(d.get("currentSize") or d.get("current_size")),
        total_size=_f(d.get("totalSize") or d.get("total_size")),
        mergeable=_b(d.get("mergeable", False)),
        raw=d,
    )


class V2Adapter:
    def __init__(self, base_url: str = BASE_URL, session: aiohttp.ClientSession | None = None):
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "V2Adapter":
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    async def _fetch_page(self, url: str, params: dict) -> dict:
        from src.utils.polymarket_rate_limit import respect_retry_after
        assert self._session, "Use V2Adapter as async context manager"
        async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            await respect_retry_after(resp)
            resp.raise_for_status()
            return await resp.json()

    async def fetch_positions(
        self,
        address: str,
        status: Literal["OPEN", "REDEEMABLE", "CLOSED"] = "OPEN",
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        params: dict = {"proxyWallet": address, "status": status}
        rows: list[PositionRow] = []
        while True:
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
            cursor = envelope.get("nextCursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return rows

    async def fetch_positions_by_conditions(
        self,
        address: str,
        condition_ids: list[str],
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        rows: list[PositionRow] = []
        chunks = [condition_ids[i:i+_BATCH] for i in range(0, len(condition_ids), _BATCH)]
        for chunk in chunks:
            params: dict = {"proxyWallet": address, "conditionIds": ",".join(chunk)}
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
        return rows
