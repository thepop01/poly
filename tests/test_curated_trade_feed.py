# tests/test_curated_trade_feed.py
import pytest
from src.workers.curated_trade_feed import trade_to_row

def test_trade_to_row_maps_fields():
    t = {
        "wallet": "0xabc", "transactionHash": "0xdead", "conditionId": "0xcid",
        "side": "BUY", "price": 0.4, "size": 100.0, "usd_volume": 40.0,
        "timestamp": 1700000000, "title": "Team A wins", "category": "SPORTS",
        "subcategory": "NFL", "blockNumber": 555, "outcome": "Yes",
    }
    row = trade_to_row(t, log_index=3)
    assert row["tx_hash"] == "0xdead"
    assert row["log_index"] == 3
    assert row["wallet_address"] == "0xabc"
    assert row["amount_usdc"] == 40.0
    assert row["block_number"] == 555
    assert row["traded_at"] is not None  # epoch converted to datetime

import os, asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")

@pytest.mark.asyncio
async def test_upsert_is_idempotent():
    c = await asyncpg.connect(DB_URL)
    tx = c.transaction(); await tx.start()
    row = dict(tx_hash="0xfeed", log_index=0, wallet_address="0x"+"dd"*20,
               condition_id="0x1", outcome="Yes", side="BUY", price=0.5, size=10,
               amount_usdc=5, traded_at=None, market_name="m", category="SPORTS",
               subcategory=None, block_number=1)
    sql = """INSERT INTO curated_trades (tx_hash,log_index,wallet_address,condition_id,outcome,side,price,size,amount_usdc,traded_at,market_name,category,subcategory,block_number)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) ON CONFLICT (tx_hash,log_index) DO NOTHING"""
    args = list(row.values())
    await c.execute(sql, *args)
    await c.execute(sql, *args)  # second insert must be a no-op
    n = await c.fetchval("SELECT COUNT(*) FROM curated_trades WHERE tx_hash='0xfeed'")
    assert n == 1
    await tx.rollback(); await c.close()
