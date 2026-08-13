import unittest
from datetime import datetime, timezone
from src.workers.deposit_tracker import _parse_block_ts


class TestDepositTracker(unittest.TestCase):
    def test_parse_block_ts_hex(self):
        result = _parse_block_ts("0x64b5f3e0")
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.year, 2023)

    def test_parse_block_ts_int(self):
        result = _parse_block_ts(1689635808)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2023)

    def test_parse_block_ts_none(self):
        result = _parse_block_ts(None)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
