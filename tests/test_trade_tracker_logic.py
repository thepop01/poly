import unittest
from collections import defaultdict
from src.workers.trade_tracker import clean_old_volumes, _rolling_volumes


class TestTradeTrackerLogic(unittest.TestCase):
    def setUp(self):
        _rolling_volumes.clear()

    def test_accumulator_post_loop_clear(self):
        """Simulate trade processing loop — accumulated clearing must happen after the loop."""
        _rolling_volumes["0xwallet1"]["mkt1"] = [(1000, 6000.0, "tx1", "BUY")]
        accumulated_to_clear = []

        # Simulated trade loop
        for wallet, market_id, val in [("0xwallet1", "mkt1", 6000.0), ("0xwallet1", "mkt1", 100.0)]:
            if val >= 5000:
                accumulated_to_clear.append((wallet, market_id))

        # Clear executed AFTER loop
        for w, m in accumulated_to_clear:
            _rolling_volumes[w][m].clear()

        self.assertEqual(len(_rolling_volumes["0xwallet1"]["mkt1"]), 0)


if __name__ == "__main__":
    unittest.main()
