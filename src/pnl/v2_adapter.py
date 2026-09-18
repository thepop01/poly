"""Polymarket v2 Data API adapter — strict field parsing, cursor pagination.

Design rules:
- Never use `field_a or field_b` for numeric values: drops legitimate zeros.
- Never default missing/malformed money to 0.0: use MISSING sentinel.
- outcome_index=0 is valid: must not be treated as falsey.
- Every numeric field carries a validity flag for the invariant layer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import aiohttp

BASE_URL = "https://data-api.polymarket.com"
_BATCH = 20

# Sentinel: distinguishes "field absent" from "field = 0"
MISSING = object()


def _first_present(row: dict, *names: str) -> Any:
    """Return the first key that is present AND non-None. Returns MISSING if none found."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return MISSING


def _parse_decimal(raw: Any) -> tuple[float | None, bool, bool]:
    """Return (value, present, valid).

    present=False: field was absent or None.
    valid=False:   field was present but could not be parsed as a finite number.
    value=None:    when present=False or valid=False.
    """
    if raw is MISSING or raw is None:
        return None, False, False
    try:
        v = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, True, False
    if not math.isfinite(v):
        return None, True, False
    return v, True, True


def _parse_int(raw: Any) -> int | None:
    """Parse int, returning None for absent/invalid (including preserving 0)."""
    if raw is MISSING or raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() in {"true", "1", "yes"}
    return bool(raw) if raw is not MISSING else False


@dataclass
class PositionRow:
    # Identity
    proxy_wallet: str
    condition_id: str
    event_id: str | None
    status: str                    # OPEN | REDEEMABLE | CLOSED
    outcome_index: int | None      # 0 is valid
    outcome: str | None            # string label e.g. "Yes"
    asset_token_id: str | None     # ERC-1155 token id

    # PnL — each field carries presence + validity flags
    source_total_pnl: float | None
    source_total_pnl_present: bool
    source_total_pnl_valid: bool

    realized_pnl: float | None
    realized_pnl_present: bool
    realized_pnl_valid: bool

    unrealized_pnl: float | None
    unrealized_pnl_present: bool
    unrealized_pnl_valid: bool

    # Cost
    entry_cost_usdc: float | None
    entry_cost_usdc_present: bool

    total_cost_usdc: float | None
    total_cost_usdc_present: bool

    entry_fees_usdc: float | None
    entry_fees_usdc_present: bool

    avg_price: float | None
    avg_price_present: bool

    # Size
    current_size: float | None
    current_size_present: bool

    total_size: float | None
    total_size_present: bool

    # Flags
    redeemable: bool | None
    mergeable: bool

    # Raw payload (for staging/audit)
    raw: dict = field(repr=False)


def _parse_row(d: dict) -> PositionRow:
    """Parse one API dict into a PositionRow with explicit validity metadata."""

    def _pnl(camel: str, snake: str) -> tuple[float | None, bool, bool]:
        return _parse_decimal(_first_present(d, camel, snake))

    def _cost(camel: str, snake: str) -> tuple[float | None, bool]:
        v, present, valid = _parse_decimal(_first_present(d, camel, snake))
        return v if valid else None, present

    # outcome_index: use explicit None-check, not `or`, because 0 is valid
    raw_oi = _first_present(d, "outcomeIndex", "outcome_index")
    outcome_index = _parse_int(raw_oi)

    # asset_token_id: never pass through float (precision loss on 77-digit tokens)
    raw_token = _first_present(d, "assetId", "asset_token_id", "asset")
    asset_token_id = None
    if raw_token is not MISSING and raw_token is not None:
        token_str = str(raw_token).strip()
        if token_str.isdigit() or token_str.startswith("0x"):
            asset_token_id = token_str

    tp, tp_p, tp_v = _pnl("totalPnl", "total_pnl")
    rp, rp_p, rp_v = _pnl("realizedPnl", "realized_pnl")
    up, up_p, up_v = _pnl("unrealizedPnl", "unrealized_pnl")

    ec, ec_p = _cost("entryCostUsdc", "entry_cost_usdc")
    tc, tc_p = _cost("totalCostUsdc", "total_cost_usdc")
    ef, ef_p = _cost("entryFeesUsdc", "entry_fees_usdc")
    ap, ap_p = _cost("avgPrice", "avg_price")
    cs, cs_p = _cost("currentSize", "current_size")
    ts, ts_p = _cost("totalSize", "total_size")

    raw_redeemable = _first_present(d, "redeemable")
    redeemable = _parse_bool(raw_redeemable) if raw_redeemable is not MISSING else None

    return PositionRow(
        proxy_wallet=str(_first_present(d, "proxyWallet", "proxy_wallet") or ""),
        condition_id=str(_first_present(d, "conditionId", "condition_id") or ""),
        event_id=(_first_present(d, "eventId", "event_id") or None),
        status=str(_first_present(d, "status") or "OPEN").upper(),
        outcome_index=outcome_index,
        outcome=str(_first_present(d, "outcome") or "") or None,
        asset_token_id=asset_token_id,
        source_total_pnl=tp, source_total_pnl_present=tp_p, source_total_pnl_valid=tp_v,
        realized_pnl=rp, realized_pnl_present=rp_p, realized_pnl_valid=rp_v,
        unrealized_pnl=up, unrealized_pnl_present=up_p, unrealized_pnl_valid=up_v,
        entry_cost_usdc=ec, entry_cost_usdc_present=ec_p,
        total_cost_usdc=tc, total_cost_usdc_present=tc_p,
        entry_fees_usdc=ef, entry_fees_usdc_present=ef_p,
        avg_price=ap, avg_price_present=ap_p,
        current_size=cs, current_size_present=cs_p,
        total_size=ts, total_size_present=ts_p,
        redeemable=redeemable,
        mergeable=_parse_bool(_first_present(d, "mergeable")),
        raw=d,
    )


class V2Adapter:
    def __init__(self, base_url: str = BASE_URL,
                 session: aiohttp.ClientSession | None = None):
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
        async with self._session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            await respect_retry_after(resp)
            resp.raise_for_status()
            return await resp.json()

    async def _paginate(self, url: str, base_params: dict) -> list[PositionRow]:
        """Cursor-paginate to completion, guarding against infinite loops."""
        rows: list[PositionRow] = []
        params = dict(base_params)
        seen_cursors: set[str] = set()
        while True:
            envelope = await self._fetch_page(url, params)
            for d in envelope.get("data") or []:
                rows.append(_parse_row(d))
            cursor = envelope.get("nextCursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise RuntimeError(f"Cursor loop detected: {cursor}")
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        return rows

    async def fetch_positions(
        self,
        address: str,
        status: Literal["OPEN", "REDEEMABLE", "CLOSED"] = "OPEN",
    ) -> list[PositionRow]:
        url = f"{self._base_url}/data-api/v2/positions"
        return await self._paginate(url, {"proxyWallet": address, "status": status})

    async def fetch_positions_by_conditions(
        self,
        address: str,
        condition_ids: list[str],
    ) -> list[PositionRow]:
        """Fetch by condition IDs in batches of ≤20, paginating each batch."""
        url = f"{self._base_url}/data-api/v2/positions"
        rows: list[PositionRow] = []
        chunks = [
            condition_ids[i:i + _BATCH]
            for i in range(0, len(condition_ids), _BATCH)
        ]
        for chunk in chunks:
            chunk_rows = await self._paginate(
                url, {"proxyWallet": address, "conditionIds": ",".join(chunk)}
            )
            rows.extend(chunk_rows)
        return rows
