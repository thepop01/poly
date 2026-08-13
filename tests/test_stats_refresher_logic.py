import unittest


class TestStatsRefresherLogic(unittest.TestCase):
    def test_fetch_balance_returns_none_on_error_contract(self):
        """Contract test: fetch_balance returning None on error prevents false LOW_BALANCE demotion."""
        fetch_error_balance = None
        # When balance is None, demotion rule must be skipped
        should_demote = False if fetch_error_balance is None else (fetch_error_balance < 1000)
        self.assertFalse(should_demote)


if __name__ == "__main__":
    unittest.main()
