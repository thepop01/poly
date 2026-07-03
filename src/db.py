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

DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "5"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "30"))


async def get_pool() -> asyncpg.Pool:
    """Return a shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX)
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db(pool: asyncpg.Pool) -> None:
    """Database initialization is now handled by Alembic migrations."""
    import logging
    logger = logging.getLogger("db")
    logger.info("Database schema is managed by Alembic. Skipping manual init.")
