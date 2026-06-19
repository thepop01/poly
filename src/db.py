"""Database connection pool and schema initialization."""

import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

_pool: asyncpg.Pool | None = None

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgres://poly_user:poly_password@localhost:5432/poly_db",
)


async def get_pool() -> asyncpg.Pool:
    """Return a shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db(pool: asyncpg.Pool) -> None:
    """Apply the schema.sql file to the database (idempotent)."""
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
