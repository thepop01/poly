from src.pnl.rules import parse_num, cost_basis, CostRule, is_winning_pnl
import pytest


def test_parse_num_handles_none_and_strings():
    assert parse_num(None) == 0.0
    assert parse_num("") == 0.0
    assert parse_num("1.5") == 1.5
    assert parse_num(3) == 3.0
    assert parse_num("garbage") == 0.0


def test_position_wins_are_not_grouped_by_condition_id():
    rows = [
        {"conditionId": "0xaa", "outcome": "Yes", "realizedPnl": 25},
        {"conditionId": "0xaa", "outcome": "No", "realizedPnl": -20},
    ]
    assert sum(is_winning_pnl(row["realizedPnl"]) for row in rows) == 1
    assert len(rows) == 2


def test_zero_pnl_is_not_a_win():
    assert is_winning_pnl(0) is False


def test_zero_bought_has_no_cost_basis():
    # Minted via splitPosition: CLOB recorded no purchase, so no cash was spent.
    row = {"totalBought": 0, "avgPrice": 0.5, "initialValue": 1_010_133.42}
    cost, rule = cost_basis(row)
    assert cost == 0.0
    assert rule is CostRule.ZERO_BOUGHT


def test_normal_buy_uses_shares_times_price():
    row = {"totalBought": 1000, "avgPrice": 0.25, "initialValue": 250.0}
    cost, rule = cost_basis(row)
    assert cost == 250.0
    assert rule is CostRule.CASH_SPENT


def test_cost_is_capped_by_initial_value_when_lower():
    # Guards against inflated totalBought * avgPrice products.
    row = {"totalBought": 1000, "avgPrice": 0.90, "initialValue": 400.0}
    cost, rule = cost_basis(row)
    assert cost == 400.0
    assert rule is CostRule.CASH_SPENT


def test_initial_value_of_zero_does_not_cap():
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 0}
    cost, rule = cost_basis(row)
    assert cost == 300.0
    assert rule is CostRule.CASH_SPENT


def test_synthetic_mint_price_is_detected_but_cost_retained_by_default():
    # avgPrice exactly 0.50 with nothing ever sold is Polymarket's synthetic
    # mint estimate. It is only safe to drop when the paired leg is absent,
    # which is decided later by the pairing pass -- not here.
    row = {"totalBought": 2_020_266, "avgPrice": 0.5, "totalSold": 0,
           "initialValue": 1_010_133.0}
    cost, rule = cost_basis(row)
    assert rule is CostRule.SYNTHETIC_MINT
    assert cost == 1_010_133.0


def test_synthetic_detection_requires_nothing_sold():
    row = {"totalBought": 1000, "avgPrice": 0.5, "totalSold": 400,
           "initialValue": 500.0}
    _, rule = cost_basis(row)
    assert rule is CostRule.CASH_SPENT


from src.pnl.rules import closed_contribution, open_contribution


def test_closed_winner_keeps_its_realized_pnl():
    row = {"totalBought": 1000, "avgPrice": 0.40, "initialValue": 400.0,
           "realizedPnl": 600.0}
    assert closed_contribution(row) == 600.0


def test_closed_loss_is_floored_at_cash_spent():
    # Polymarket reports -1,010,133 on a position that cost 400 in cash.
    row = {"totalBought": 1000, "avgPrice": 0.40, "initialValue": 400.0,
           "realizedPnl": -1_010_133.42}
    assert closed_contribution(row) == -400.0


def test_closed_minted_loss_becomes_zero():
    row = {"totalBought": 0, "avgPrice": 0.50, "initialValue": 1_010_133.42,
           "realizedPnl": -1_010_133.42}
    assert closed_contribution(row) == 0.0


def test_open_position_marks_to_market_against_cost():
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 300.0,
           "currentValue": 500.0}
    assert open_contribution(row) == 200.0


def test_open_contribution_includes_profit_from_partial_sells():
    row = {"totalBought": 1000, "avgPrice": 0.50, "initialValue": 200.0,
           "currentValue": 250.0, "realizedPnl": 75.0}
    assert open_contribution(row) == 125.0


def test_open_cost_uses_remaining_initial_value_after_partial_sells():
    row = {"totalBought": 1000, "avgPrice": 0.50, "initialValue": 200.0,
           "currentValue": 0.0, "realizedPnl": 250.0, "redeemable": True}
    assert open_contribution(row) == 50.0


def test_unredeemed_winner_credits_full_payout_minus_cost():
    # Market resolved in our favour; currentValue is size * 1.00, unclaimed.
    row = {"totalBought": 1000, "avgPrice": 0.30, "initialValue": 300.0,
           "currentValue": 1000.0, "redeemable": True}
    assert open_contribution(row) == 700.0


def test_open_minted_loser_contributes_zero_not_a_phantom_loss():
    # This single rule is what previously injected tens of millions in
    # fake losses on the open side.
    row = {"totalBought": 0, "avgPrice": 0.50, "initialValue": 1_010_133.42,
           "currentValue": 0.0, "redeemable": True}
    assert open_contribution(row) == 0.0


@pytest.mark.asyncio
async def test_redeemable_sync_uses_remaining_cost_and_partial_sell_pnl():
    from src.workers.positions_open_backfill import sync_redeemable_positions

    class FakeConn:
        def __init__(self):
            self.rows = None

        async def executemany(self, _sql, rows):
            self.rows = rows

    conn = FakeConn()
    position = {
        "conditionId": "0xpartial",
        "outcome": "Yes",
        "redeemable": True,
        "totalBought": 1000,
        "avgPrice": 0.50,
        "initialValue": 200,
        "currentValue": 0,
        "realizedPnl": 250,
        "size": 400,
        "endDate": "2026-08-01",
    }
    count = await sync_redeemable_positions(
        conn, None, "0xwallet", [position], set()
    )
    assert count == 1
    assert conn.rows[0][7] == 50.0
    assert conn.rows[0][4] == 1.0
