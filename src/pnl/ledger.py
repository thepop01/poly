"""Pure canonical position accounting and source-row normalization.

This module is deliberately additive.  It does not replace the existing
``src.pnl.rules`` compatibility surface; later workers can import this module
and move to the canonical snake_case contract one at a time.

Inputs may be API dictionaries, database dictionaries, or asyncpg-like records.
No database, network, or current-time access occurs here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import math
import re
from typing import Any


_MISSING = object()
ZERO_BOUGHT_EPSILON = 0.01
SYNTHETIC_MINT_LOW = 0.4995
SYNTHETIC_MINT_HIGH = 0.5005
PRICE_BUCKETS = (
    "below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c",
)


def _row_dict(row: Any) -> dict[str, Any]:
    """Copy a mapping-like row, including asyncpg.Record, into a plain dict."""
    if isinstance(row, Mapping):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        try:
            return {key: row[key] for key in keys()}
        except (KeyError, TypeError, IndexError):
            pass
    items = getattr(row, "items", None)
    if callable(items):
        return dict(items())
    raise TypeError("position row must be a mapping or asyncpg-like record")


def _first(row: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    """Return the first *non-null* alias, preserving falsey values."""
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _strict_number(value: Any, *, nonnegative: bool = False) -> tuple[float | None, bool]:
    """Parse a number while retaining whether the source value was valid."""
    if value is _MISSING or value is None or isinstance(value, bool):
        return None, False
    if isinstance(value, str) and not value.strip():
        return None, False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, False
    if not math.isfinite(number) or (nonnegative and number < 0):
        return None, False
    return number, True


def parse_num(value: Any) -> float | None:
    """Strict numeric parser; malformed and missing input is explicit no-data."""
    return _strict_number(value)[0]


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return default


def _parse_timestamp(value: Any) -> datetime | None:
    if value is _MISSING or value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                return None
            if number >= 100_000_000_000:
                number /= 1000
            return datetime.fromtimestamp(number, tz=timezone.utc)
        text = str(value).strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return _parse_timestamp(float(text))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _explicit_price(value: Any, row: Mapping[str, Any]) -> tuple[float | None, bool]:
    """Parse a 0..1 price; cents are accepted only with an explicit unit."""
    number, valid = _strict_number(value)
    if not valid or number is None or number < 0:
        return None, False
    if number <= 1:
        return number, True
    unit = _first(row, "price_unit", "priceUnit", default=None)
    cents_flag = _first(row, "price_is_cents", "priceIsCents", default=None)
    explicit_cents = (
        isinstance(unit, str) and unit.strip().casefold() in {"cent", "cents"}
    ) or _parse_bool(cents_flag)
    if explicit_cents and number <= 100:
        return number / 100.0, True
    # Values above one without an explicit unit are ambiguous, not cheap.
    return None, False


def _normalize_token(value: Any) -> str | None:
    """Keep token IDs exact as strings; never pass them through float."""
    if value is _MISSING or value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return None  # a float cannot guarantee a 77-digit token's identity
    if not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() or re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return text
    return None


def _looks_like_token(value: Any) -> bool:
    return _normalize_token(value) is not None


def is_parlay_position(row: Any) -> bool:
    """Use explicit flags/IDs first and only deliberate title markers."""
    source = _row_dict(row)
    flags = ("is_parlay", "isParlay", "is_combo", "isCombo", "parlay", "combo")
    present = [name for name in flags if name in source and source[name] is not None]
    if present:
        return any(_parse_bool(source[name]) for name in present)
    ids = ("parlay_id", "parlayId", "combo_id", "comboId", "combo_condition_id", "comboConditionId")
    if any(_text(source.get(name)) for name in ids):
        return True
    condition = _text(_first(source, "condition_id", "conditionId", default=""))
    if condition.lower().startswith("0x03") and len(condition) >= 66 and condition.endswith("0" * 10):
        return True
    title = _text(_first(source, "title", "market_title", "market", default=""))
    return bool(re.search(r"\b(?:PARLAY|COMBO)\b", title, re.IGNORECASE))


def _artifact_flag(source: Mapping[str, Any], provenance: str) -> bool:
    explicit = _first(
        source, "synthetic_artifact", "syntheticArtifact", "is_synthetic_artifact",
        "isSyntheticArtifact", default=None,
    )
    if explicit is not None:
        return _parse_bool(explicit)
    quality = _text(_first(source, "data_quality_flag", "dataQualityFlag", default="")).casefold()
    if quality in {"minted_shares", "mixed_minted_shares", "synthetic_liquidation_artifact", "synthetic_mint"}:
        return True
    return provenance.casefold() in {"synthetic_artifact", "synthetic_mint", "legacy_synthetic_mint"}


def normalize_closed_row(row: Any) -> dict[str, Any]:
    """Normalize one source row to a snake_case contract with validity metadata.

    ``None`` means no-data; ``invalid_fields`` records malformed, missing, or
    ambiguous input instead of turning it into a zero or an artificially cheap
    price.  Explicit ``price_unit='cents'`` is the only cents conversion.
    """
    source = _row_dict(row)
    provenance = _text(_first(source, "provenance", "pnl_provenance", "source_provenance", default=""))
    source_name = _text(_first(source, "source", "source_type", "sourceType", "pnl_source", default=""))

    raw_source_pnl = _first(
        source, "source_realized_pnl", "sourceRealizedPnl", "raw_realized_pnl", "rawRealizedPnl",
        "realized_pnl_raw", "realizedPnlRaw", default=_MISSING,
    )
    if raw_source_pnl is _MISSING:
        raw_source_pnl = _first(source, "realized_pnl", "realizedPnl", "cash_pnl", "cashPnl", default=_MISSING)
    raw_realized = _first(source, "realized_pnl", "realizedPnl", default=raw_source_pnl)

    validity: dict[str, bool] = {}
    invalid: list[str] = []

    def number(field: str, *aliases: str, nonnegative: bool = False) -> float | None:
        raw = _first(source, *aliases, default=_MISSING)
        value, valid = _strict_number(raw, nonnegative=nonnegative)
        validity[field] = valid
        if not valid:
            invalid.append(field)
        return value

    total_bought = number("total_bought", "total_bought", "totalBought", nonnegative=True)
    total_sold = number("total_sold", "total_sold", "totalSold", nonnegative=True)
    size = number("size", "size", "shares", "tokens", nonnegative=True)
    initial_value = number("initial_value", "initial_value", "initialValue", "invested", nonnegative=True)
    current_value = number("current_value", "current_value", "currentValue", nonnegative=True)
    settlement_value = number(
        "settlement_value", "settlement_value", "settlementValue", "settlement_payout",
        "settlementPayout", "payout", "redeem_value", "redeemValue", nonnegative=True,
    )
    source_pnl, source_pnl_valid = _strict_number(raw_source_pnl)
    realized_pnl, realized_valid = _strict_number(raw_realized)
    validity["source_realized_pnl"] = source_pnl_valid
    validity["realized_pnl"] = realized_valid
    if not source_pnl_valid:
        invalid.append("source_realized_pnl")

    avg_buy_price, buy_price_valid = _explicit_price(
        _first(source, "avg_buy_price", "avgBuyPrice", "avg_price", "avgPrice", default=_MISSING), source,
    )
    avg_sell_price, sell_price_valid = _explicit_price(
        _first(source, "avg_sell_price", "avgSellPrice", default=_MISSING), source,
    )
    validity["avg_buy_price"] = buy_price_valid
    validity["avg_sell_price"] = sell_price_valid
    if not buy_price_valid:
        invalid.append("avg_buy_price")
    if not sell_price_valid:
        invalid.append("avg_sell_price")

    materialized_raw = _first(
        source, "materialized_contribution", "materializedContribution", "stored_contribution",
        "storedContribution", "ledger_contribution", "ledgerContribution", default=_MISSING,
    )
    materialized, materialized_valid = _strict_number(materialized_raw)
    legacy_transformed = _parse_bool(_first(source, "legacy_transformed", "legacyTransformed", default=False))
    marker = provenance.casefold().replace("-", "_").replace(" ", "_")
    legacy_transformed = legacy_transformed or marker in {
        "legacy_redeemable_transformed", "legacy_transformed_settlement", "settlement_included",
    }
    settlement_explicit = _first(
        source, "settlement_included", "settlementIncluded", "payout_included", "payoutIncluded",
        "realized_includes_settlement", "realizedIncludesSettlement", default=_MISSING,
    )
    settlement_included = (
        _parse_bool(settlement_explicit)
        if settlement_explicit is not _MISSING
        else marker.endswith("_settlement_included") or marker in {"settlement_included", "legacy_redeemable_transformed"}
    )
    if materialized_raw is _MISSING and settlement_included and legacy_transformed:
        # Legacy transformed rows materialized their contribution in realized_pnl.
        materialized = realized_pnl if realized_valid else source_pnl
        materialized_valid = realized_valid or source_pnl_valid

    numeric_validity = dict(validity)
    for field, valid in (("materialized_contribution", materialized_valid),):
        numeric_validity[field] = valid
        if materialized_raw is not _MISSING and not valid:
            invalid.append(field)

    raw_token = _first(source, "asset_token_id", "assetTokenId", default=_MISSING)
    token = _normalize_token(raw_token)
    asset_raw = _first(source, "asset", "asset_id", "assetId", default=_MISSING)
    # Missing provenance identifiers are stable empty values, never the
    # internal sentinel (which would leak a process-dependent object repr).
    source_asset = _text(_first(source, "source_asset", "sourceAsset", default=""))
    if not source_asset and asset_raw is not _MISSING:
        source_asset = _text(asset_raw)
    if token is None and _looks_like_token(asset_raw):
        token = _normalize_token(asset_raw)

    normalized: dict[str, Any] = {
        "address": _text(_first(source, "address", "wallet_address", "walletAddress", "user", default="")),
        "condition_id": _text(_first(source, "condition_id", "conditionId", default="")),
        "outcome": _text(_first(source, "outcome", "outcome_label", "outcomeLabel", default="")),
        "source_asset": source_asset,
        "asset_token_id": token,
        "total_bought": total_bought,
        "total_sold": total_sold,
        "size": size,
        "avg_buy_price": avg_buy_price,
        "avg_sell_price": avg_sell_price,
        "initial_value": initial_value,
        "current_value": current_value,
        "settlement_value": settlement_value,
        "source_realized_pnl": source_pnl,
        "realized_pnl": realized_pnl,
        "materialized_contribution": materialized,
        "source": source_name,
        "provenance": provenance,
        "settlement_included": settlement_included,
        "legacy_transformed": legacy_transformed,
        "is_redeemable": _parse_bool(_first(source, "is_redeemable", "isRedeemable", "redeemable", default=False)),
        "synthetic_artifact": _artifact_flag(source, provenance),
        "is_parlay": is_parlay_position(source),
        "metrics_eligible": _parse_bool(_first(source, "metrics_eligible", "metricsEligible", "eligible", default=True), True),
        "data_quality_flag": _text(_first(source, "data_quality_flag", "dataQualityFlag", default="")) or None,
        "category": _text(_first(source, "category", default="")),
        "subcategory": _text(_first(source, "subcategory", default="")),
        "league": _text(_first(source, "league", default="")),
        "title": _text(_first(source, "title", "market_title", "market", default="")),
        "event_slug": _text(_first(source, "event_slug", "eventSlug", default="")),
        "closed_at": _parse_timestamp(_first(source, "closed_at", "closedAt", default=_MISSING)),
        "opened_at": _parse_timestamp(_first(source, "opened_at", "openedAt", "entry_at", "entryAt", default=_MISSING)),
        "resolved_at": _parse_timestamp(_first(source, "resolved_at", "resolvedAt", default=_MISSING)),
        "timestamp": _parse_timestamp(_first(source, "timestamp", "event_at", "eventAt", default=_MISSING)),
        "numeric_validity": numeric_validity,
        "invalid_fields": tuple(dict.fromkeys(invalid)),
    }
    normalized["is_valid"] = not normalized["invalid_fields"]
    return normalized


def is_synthetic_mint(row: Any) -> bool:
    normalized = normalize_closed_row(row)
    price = normalized["avg_buy_price"]
    return (
        price is not None
        and SYNTHETIC_MINT_LOW <= price <= SYNTHETIC_MINT_HIGH
        and normalized["total_sold"] == 0
    )


def _cost_basis(normalized: Mapping[str, Any]) -> float | None:
    bought = normalized["total_bought"]
    price = normalized["avg_buy_price"]
    if bought is None:
        return None
    if bought <= ZERO_BOUGHT_EPSILON:
        return 0.0
    if price is None:
        return None
    cost = bought * price
    initial = normalized["initial_value"]
    if initial is not None and initial > 0:
        cost = min(cost, initial)
    return cost


def cost_basis(row: Any) -> float | None:
    return _cost_basis(normalize_closed_row(row))


def row_volume_usd(row: Any) -> float | None:
    normalized = normalize_closed_row(row)
    bought = normalized["total_bought"]
    price = normalized["avg_buy_price"]
    if bought is None or price is None:
        return None
    return bought * price


def row_win(contribution: Any) -> bool:
    value, valid = _strict_number(contribution)
    return bool(valid and value is not None and value > 0)


def _floor(value: float, cost: float | None) -> float | None:
    return None if cost is None else max(value, -cost)


def _legacy_materialized(normalized: Mapping[str, Any]) -> float | None:
    if normalized["settlement_included"]:
        stored = normalized["materialized_contribution"]
        if stored is not None:
            return stored
        if normalized["legacy_transformed"]:
            return normalized["source_realized_pnl"]
    return None


def closed_ledger_contribution(row: Any) -> float | None:
    normalized = normalize_closed_row(row)
    stored = _legacy_materialized(normalized)
    if stored is not None:
        return stored
    source = normalized["source_realized_pnl"]
    if source is None:
        return None
    return _floor(source, _cost_basis(normalized))


def _suppress_zero_cost_negative(normalized: Mapping[str, Any], source: float) -> float:
    if source < 0 and _cost_basis(normalized) == 0 and (
        normalized["is_redeemable"] or normalized["synthetic_artifact"]
    ):
        return 0.0
    return source


def redeemable_ledger_contribution(row: Any) -> float | None:
    normalized = normalize_closed_row(row)
    stored = _legacy_materialized(normalized)
    if stored is not None:
        return stored  # already materialized; never subtract cost/current again
    source = normalized["source_realized_pnl"]
    if source is None:
        return None
    cost = _cost_basis(normalized)
    source = _suppress_zero_cost_negative(normalized, source)
    settlement = normalized["settlement_value"]
    if settlement is None:
        settlement = normalized["current_value"]
    if settlement is None:
        return None
    if cost is None:
        return None
    return _floor(source + settlement - cost, cost)


def open_mark_to_market_contribution(row: Any) -> float | None:
    normalized = normalize_closed_row(row)
    stored = _legacy_materialized(normalized)
    if stored is not None:
        return stored
    source = normalized["source_realized_pnl"]
    current = normalized["current_value"]
    if source is None or current is None:
        return None
    cost = _cost_basis(normalized)
    source = _suppress_zero_cost_negative(normalized, source)
    if cost is None:
        return None
    total = source + current - cost
    # A zero-cost ordinary row has no cash-loss floor to apply.  Preserve its
    # observed source value; only explicit redeemable/synthetic artifacts get
    # the zero-cost negative suppression above.
    if cost == 0 and not (normalized["is_redeemable"] or normalized["synthetic_artifact"]):
        return total
    return _floor(total, cost)


def _price_value(price: Any) -> float | None:
    value, valid = _strict_number(price)
    if not valid or value is None or value < 0 or value > 1:
        return None
    return value


def bucket_for_price(price: Any) -> str | None:
    value = _price_value(price)
    if value is None:
        return None
    if value < 0.15:
        return "below_15c"
    if value < 0.30:
        return "15_30c"
    if value < 0.45:
        return "30_45c"
    if value < 0.60:
        return "45_60c"
    if value < 0.75:
        return "60_75c"
    return "above_75c"


def roi_pct(pnl: Any, volume: Any, *, minimum_volume: float = 10.0) -> float | None:
    pnl_value, pnl_valid = _strict_number(pnl)
    volume_value, volume_valid = _strict_number(volume, nonnegative=True)
    if not pnl_valid or not volume_valid or pnl_value is None or volume_value is None or volume_value < minimum_volume:
        return None
    return max(-100.0, min(pnl_value / volume_value * 100.0, 10_000.0))


def position_key(row: Any) -> tuple[str, str, str]:
    normalized = normalize_closed_row(row)
    return (
        normalized["condition_id"],
        normalized["outcome"],
        normalized["asset_token_id"] or normalized["source_asset"],
    )


def position_identity(row: Any) -> tuple[str, str, str, str]:
    normalized = normalize_closed_row(row)
    return (normalized["address"], *position_key(normalized))


def row_identity(row: Any) -> tuple[str, str, str, str]:
    return position_identity(row)


def position_order_key(row: Any) -> tuple[Any, ...]:
    """Closed-at descending, NULLS LAST, with stable identity tie-breakers."""
    normalized = normalize_closed_row(row)
    closed_at = normalized["closed_at"]
    timestamp_sort = -closed_at.timestamp() if closed_at is not None else 0.0
    missing_sort = 1 if closed_at is None else 0
    address, condition, outcome, token = position_identity(normalized)
    return (missing_sort, timestamp_sort, token, condition, outcome, address)


def ordered_positions(rows: Sequence[Any], *, descending: bool = True) -> list[dict[str, Any]]:
    """Normalize and deterministically order positions without mutating input."""
    normalized = [normalize_closed_row(row) for row in rows]
    # The canonical order is descending closed_at/NULLS LAST.  ``descending``
    # remains as a compatibility option, but does not invert NULL placement.
    if descending:
        return sorted(normalized, key=position_order_key)
    return sorted(normalized, key=lambda row: (position_order_key(row)[0], -position_order_key(row)[1], position_order_key(row)[2:]))


# Names used by existing workers can be adopted later without changing math.
closed_contribution = closed_ledger_contribution
open_contribution = open_mark_to_market_contribution
is_winning_pnl = row_win
