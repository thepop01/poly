"""Tests for the incremental watermark merge in wallet_market_activity_v2."""

import datetime

import pytest


def _ts(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)


@pytest.mark.asyncio
async def test_incremental_merge_skips_fresh_rows(test_pool):
    from src.scripts.backfill_market_activity import incremental_aggregate_wallet
    addr = "0x000000000000000000000000000000000000aaaa"
    cid = "0x" + "aa" * 31 + "01"
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO wallets_v2 (address) VALUES ($1) ON CONFLICT DO NOTHING", addr)
            snap = await conn.fetchval("""
                INSERT INTO wallet_source_snapshots_v2 (address, source, complete, fetched_at, payload_sha256)
                VALUES ($1, 'activity', TRUE, NOW(), 'dummy') RETURNING id
            """, addr)
            for i in range(8):
                await conn.execute("""
                    INSERT INTO wallet_activity_events_v2
                    (snapshot_id, address, condition_id, event_sha256, asset, outcome,
                     event_type, side, size, price, usdc_size, event_timestamp,
                     transaction_hash, payload)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """, snap, addr, cid, f'old_sha_{i}', '0', 'Yes',
                    'TRADE', 'BUY', 10, 0.5, 5,
                    _ts(2025, 1, 1 + i), f'0xtx{i}', '{}')
            n = await incremental_aggregate_wallet(test_pool, addr)
            row = await conn.fetchrow(
                "SELECT event_count FROM wallet_market_activity_v2 "
                "WHERE address=$1 AND condition_id=$2", addr, cid)
            assert row is not None, "aggregate should be created from scratch for new wallet"
            assert row["event_count"] == 8
        finally:
            await conn.execute("DELETE FROM wallet_activity_events_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallet_market_activity_v2 WHERE address=$1", addr)
            await conn.execute(
                "DELETE FROM wallet_source_snapshots_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallets_v2 WHERE address=$1", addr)


@pytest.mark.asyncio
async def test_incremental_merge_picks_up_stale_rows(test_pool):
    from src.scripts.backfill_market_activity import incremental_aggregate_wallet
    addr = "0x000000000000000000000000000000000000bbbb"
    cid = "0x" + "bb" * 31 + "02"
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO wallets_v2 (address) VALUES ($1) ON CONFLICT DO NOTHING", addr)
            snap = await conn.fetchval("""
                INSERT INTO wallet_source_snapshots_v2 (address, source, complete, fetched_at, payload_sha256)
                VALUES ($1, 'activity', TRUE, NOW(), 'dummy') RETURNING id
            """, addr)
            for i in range(8):
                await conn.execute("""
                    INSERT INTO wallet_activity_events_v2
                    (snapshot_id, address, condition_id, event_sha256, asset, outcome,
                     event_type, side, size, price, usdc_size, event_timestamp,
                     transaction_hash, payload)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """, snap, addr, cid, f'old_sha_{i}', '0', 'Yes',
                    'TRADE', 'BUY', 10, 0.5, 5,
                    _ts(2025, 1, 1 + i), f'0xtx{i}', '{}')
            for i, (etype, side, sz, pr, usdc, ts) in enumerate([
                ('TRADE', 'BUY', 10, 0.8, 8, _ts(2025, 7, 1)),
                ('TRADE', 'SELL', 5, 0.9, 4.5, _ts(2025, 7, 2)),
            ]):
                await conn.execute("""
                    INSERT INTO wallet_activity_events_v2
                    (snapshot_id, address, condition_id, event_sha256, asset, outcome,
                     event_type, side, size, price, usdc_size, event_timestamp,
                     transaction_hash, payload)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """, snap, addr, cid, f'new_sha_{i}', '0', 'Yes',
                    etype, side, sz, pr, usdc, ts, f'0xtxn{i}', '{}')
            await conn.execute("""
                INSERT INTO wallet_market_activity_v2
                (address, condition_id, outcome_token_id, outcome_label,
                 trade_buys, buy_shares, buy_cost, trade_sells, sell_shares, sell_proceeds,
                 redeem_count, redeem_usdc, split_shares, merge_shares, conversion_events,
                 reward_usdc, event_count, first_event_at, last_event_at,
                 last_event_ts, last_event_sha, updated_at)
                VALUES ($1, $2, 0, 'Yes', 8, 80, 40, 0, 0, 0,
                        0, 0, 0, 0, 0, 0, 8,
                        '2025-01-01'::timestamptz, '2025-01-08'::timestamptz,
                        1736300400, 'old_sha_7', NOW())
            """, addr, cid)
            n = await incremental_aggregate_wallet(test_pool, addr)
            row = await conn.fetchrow(
                "SELECT event_count, trade_buys, trade_sells FROM wallet_market_activity_v2 "
                "WHERE address=$1 AND condition_id=$2", addr, cid)
            assert row["event_count"] == 10, f"expected 10, got {row['event_count']}"
            assert row["trade_buys"] == 9
            assert row["trade_sells"] == 1
        finally:
            await conn.execute("DELETE FROM wallet_activity_events_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallet_market_activity_v2 WHERE address=$1", addr)
            await conn.execute(
                "DELETE FROM wallet_source_snapshots_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallets_v2 WHERE address=$1", addr)
