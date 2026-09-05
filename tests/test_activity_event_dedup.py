"""Cross-snapshot event dedup: same event refetched under a new snapshot
must not store twice (incremental resume overlap)."""

import pytest


@pytest.mark.asyncio
async def test_same_event_two_snapshots_stores_once(test_pool):
    addr = "0x000000000000000000000000000000000000dddd"
    cid = "0x" + "dd" * 31 + "04"
    async with test_pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO wallets_v2 (address) VALUES ($1) ON CONFLICT DO NOTHING", addr)
            snaps = []
            for i in range(2):
                snaps.append(await conn.fetchval("""
                    INSERT INTO wallet_source_snapshots_v2
                    (address, source, complete, fetched_at, payload_sha256)
                    VALUES ($1, 'activity', TRUE, NOW(), $2) RETURNING id
                """, addr, f"dup-{i}"))
            for snap in snaps:
                await conn.execute("""
                    INSERT INTO wallet_activity_events_v2
                    (snapshot_id, address, condition_id, event_sha256, asset, outcome,
                     event_type, side, size, price, usdc_size, event_timestamp,
                     transaction_hash, payload)
                    VALUES ($1,$2,$3,'dup_sha_1','0','Yes','TRADE','BUY',
                            10, 0.5, 5, NOW(), '0xtx', '{}')
                    ON CONFLICT (address, event_sha256) DO NOTHING
                """, snap, addr, cid)
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM wallet_activity_events_v2 WHERE address=$1", addr)
            assert n == 1, f"expected 1 row, got {n}"
        finally:
            await conn.execute("DELETE FROM wallet_activity_events_v2 WHERE address=$1", addr)
            await conn.execute(
                "DELETE FROM wallet_source_snapshots_v2 WHERE address=$1", addr)
            await conn.execute("DELETE FROM wallets_v2 WHERE address=$1", addr)
