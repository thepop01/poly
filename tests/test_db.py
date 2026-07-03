"""Tests for src.db — requires a running Postgres instance."""

import pytest
from src.db import get_pool, init_db, close_pool


@pytest.mark.asyncio
async def test_pool_creation_and_closure():
    """Verify we can create and close a connection pool."""
    pool = await get_pool()
    assert pool is not None
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    await close_pool()


@pytest.mark.asyncio
async def test_init_db_is_idempotent():
    """init_db should be safe to call multiple times (schema managed by Alembic)."""
    pool = await get_pool()
    await init_db(pool)
    await init_db(pool)
    await close_pool()
