import unittest
from src.utils.accounting import apply_fill


class TestAccounting(unittest.TestCase):
    def test_apply_fill_uses_size_key_not_token_size(self):
        """apply_fill must read 'size' not 'token_size' from trade dict."""
        trade = {"side": "BUY", "usd_volume": 100.0, "size": 200.0}
        result = apply_fill({}, trade)
        self.assertEqual(
            result["total_buy_tokens"],
            200.0,
            f"Expected 200.0 but got {result['total_buy_tokens']} — wrong key being read",
        )

    def test_apply_fill_sell_pnl_is_not_full_usd_volume(self):
        """With correct token tracking, a sell at breakeven price should have ~zero PnL."""
        state = apply_fill({}, {"side": "BUY", "usd_volume": 50.0, "size": 100.0})
        result = apply_fill(state, {"side": "SELL", "usd_volume": 50.0, "size": 100.0})
        self.assertAlmostEqual(
            result["realized_pnl"],
            0.0,
            places=2,
            msg=f"PnL should be ~0 for breakeven trade, got {result['realized_pnl']}",
        )


if __name__ == "__main__":
    unittest.main()
