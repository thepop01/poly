"""Pure position-accounting rules. No I/O, no DB, no network.

Every rule here exists because Polymarket's position payloads mix two
incompatible sources: the CLOB orderbook (which knows what was actually
bought) and the on-chain token balance (which does not). Cost basis must
never exceed the cash the CLOB actually recorded.
"""
from enum import Enum

SYNTHETIC_MINT_LOW = 0.4995
SYNTHETIC_MINT_HIGH = 0.5005
ZERO_BOUGHT_EPSILON = 0.01


class CostRule(str, Enum):
    ZERO_BOUGHT = "zero_bought"
    SYNTHETIC_MINT = "synthetic_mint"
    CASH_SPENT = "cash_spent"


def parse_num(value) -> float:
    """Coerce an API field to float. Missing/garbage becomes 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get(row: dict, camel: str, snake: str):
    """Try snake_case (v2) first, fall back to camelCase (v1/legacy)."""
    return row.get(snake) if snake in row else row.get(camel)


def is_winning_pnl(value) -> bool:
    """Classify one resolved contract row at its native position grain.

    A profitable contract row is one win. Zero and negative PnL rows are not
    wins. This intentionally does not group opposite outcomes by conditionId:
    grouping changes the denominator and destroys position-level win rates.
    """
    return parse_num(value) > 0.0


def is_synthetic_mint(row: dict) -> bool:
    """True when avgPrice is Polymarket's 0.50 mint estimate and nothing sold."""
    avg_price = parse_num(_get(row, "avgPrice", "avg_price"))
    if not (SYNTHETIC_MINT_LOW <= avg_price <= SYNTHETIC_MINT_HIGH):
        return False
    return parse_num(_get(row, "totalSold", "total_sold")) == 0.0


def cost_basis(row: dict) -> tuple[float, CostRule]:
    """Return (cost_basis_usd, rule_applied) for one position row."""
    total_bought = parse_num(_get(row, "totalBought", "total_bought"))
    avg_price = parse_num(_get(row, "avgPrice", "avg_price"))
    initial_value = parse_num(_get(row, "initialValue", "initial_value"))

    if total_bought <= ZERO_BOUGHT_EPSILON:
        return 0.0, CostRule.ZERO_BOUGHT

    cost = total_bought * avg_price
    if initial_value > 0:
        cost = min(cost, initial_value)

    if is_synthetic_mint(row):
        return cost, CostRule.SYNTHETIC_MINT

    return cost, CostRule.CASH_SPENT


def closed_contribution(row: dict) -> float:
    """PnL for a settled position: reported realized PnL, floored at cash spent.

    A position cannot lose more than the cash that entered it. Polymarket's
    realizedPnl on minted residuals violates this, which is the phantom loss.
    """
    cost, _rule = cost_basis(row)
    realized = parse_num(_get(row, "realizedPnl", "realized_pnl"))
    return max(realized, -cost)


def remaining_cost(row: dict) -> float:
    """Replaces min(initialValue, totalBought*avgPrice). current_size * avg_price is exact."""
    current_size = parse_num(_get(row, "currentSize", "current_size")) or 0.0
    avg_price    = parse_num(_get(row, "avgPrice",    "avg_price"))    or 0.0
    return current_size * avg_price


def open_contribution(row: dict) -> float:
    """PnL for a live or resolved-but-unclaimed position.

    currentValue already carries the $1.00-per-share payout for unredeemed
    winners. realizedPnl carries profit/loss from shares sold before resolution
    and must be included as well. The remaining cost basis is capped by both
    initialValue and recorded CLOB cash spend so minted shares cannot create a
    loss larger than the wallet's recorded purchases.
    """
    cost, _rule = cost_basis(row)
    return (
        parse_num(_get(row, "realizedPnl", "realized_pnl"))
        + parse_num(_get(row, "currentValue", "current_value"))
        - cost
    )
