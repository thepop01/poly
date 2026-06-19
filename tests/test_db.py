"""Tests for src.db — requires a running Postgres instance."""

import pytest
from src.db import get_pool, init_db, close_pool


@pytest.mark.asyncio
async def test_init_db_creates_tables():
    pool = await get_pool()
    await init_db(pool)
    async with pool.acquire() as conn:
        for table_name in ("events", "markets", "trades"):
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1",
                table_name,
            )
            assert count == 1, f"Table '{table_name}' was not created"
    await close_pool()


@pytest.mark.asyncio
async def test_init_db_is_idempotent():
    pool = await get_pool()
    await init_db(pool)
    await init_db(pool)  # should not raise
    await close_pool()
