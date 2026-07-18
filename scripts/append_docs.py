import os

with open("docs/history.md", "a", encoding="utf-8") as f:
    f.write("- Fixed bug where `position_value` evaluated to $0 due to `price` being `None` in the Polymarket API; now uses `currentValue` directly.\n")
    f.write("- Fixed bug where `last_trade_at` was stale for Might Cook wallets by fetching live trades from Polymarket's data API and writing to the DB.\n")
    f.write("- Added a 'copy to clipboard' button for wallet addresses in the Might Cook frontend for better UX.\n")

print("Docs appended")
