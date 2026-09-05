"""Database connection pool and schema initialization."""

import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

_pool: asyncpg.Pool | None = None

import urllib.parse

def _normalize_db_url(raw_url: str) -> tuple[str, bool | str]:
    if not raw_url:
        raw_url = "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db"
    
    # Normalize scheme
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[len("postgres://"):]
    
    parsed = urllib.parse.urlsplit(raw_url)
    hostname = parsed.hostname
    port = parsed.port or 5432
    netloc = parsed.netloc

    # Only replace localhost in host portion, never touch password/user
    if hostname == "localhost":
        user_pass = ""
        if "@" in netloc:
            user_pass = netloc.split("@")[0] + "@"
        netloc = f"{user_pass}127.0.0.1:{port}"
        parsed = parsed._replace(netloc=netloc)

    # Determine SSL mode
    qs = urllib.parse.parse_qs(parsed.query)
    ssl_mode_param = qs.get("sslmode", [None])[0] or qs.get("ssl", [None])[0]
    db_ssl_env = os.getenv("DB_SSL", "").lower()

    if db_ssl_env in ("true", "1", "require"):
        ssl_val = "require"
    elif db_ssl_env in ("false", "0", "disable"):
        ssl_val = False
    elif ssl_mode_param in ("require", "verify-ca", "verify-full"):
        ssl_val = ssl_mode_param
    elif ssl_mode_param in ("disable", "false"):
        ssl_val = False
    elif parsed.hostname and parsed.hostname not in ("127.0.0.1", "localhost"):
        ssl_val = "require"
    else:
        ssl_val = False

    return urllib.parse.urlunsplit(parsed), ssl_val

_RAW_DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db")
DATABASE_URL, DB_SSL_CONFIG = _normalize_db_url(_RAW_DB_URL)

DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "5"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "30"))


async def get_pool() -> asyncpg.Pool:
    """Return a shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            ssl=DB_SSL_CONFIG,
            min_size=DB_POOL_MIN,
            max_size=DB_POOL_MAX,
            timeout=30,
            command_timeout=60,
        )
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
