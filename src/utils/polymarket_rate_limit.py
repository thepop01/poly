"""Cross-process Polymarket Data API rate limiter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import asyncpg


async def respect_retry_after(response) -> None:
    """Sleep for the duration specified in a 429 Retry-After header."""
    if getattr(response, "status", None) != 429:
        return
    header = (response.headers or {}).get("Retry-After", "")
    try:
        wait = float(header)
        if wait > 0:
            await asyncio.sleep(wait)
    except (TypeError, ValueError):
        pass

DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
    "positions": (15.0, 15.0),
    "closed-positions": (15.0, 15.0),
    "trades": (20.0, 20.0),
    "activity": (90.0, 90.0),
}


class PostgresRateLimiter:
    """Use the migration's row-locked token buckets across worker processes."""

    def __init__(self, pool: asyncpg.Pool, limits: dict[str, tuple[float, float]] | None = None):
        self.pool = pool
        self.limits = limits or DEFAULT_LIMITS

    async def acquire(self, endpoint: str) -> None:
        rate, capacity = self.limits[endpoint]
        while True:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    now = datetime.now(timezone.utc)
                    row = await conn.fetchrow(
                        "SELECT tokens, updated_at FROM data_api_rate_limit_buckets WHERE endpoint=$1 FOR UPDATE",
                        endpoint,
                    )
                    tokens = capacity if row is None else min(
                        capacity,
                        float(row["tokens"]) + max(0.0, (now-row["updated_at"]).total_seconds()) * rate,
                    )
                    if row is None:
                        await conn.execute("INSERT INTO data_api_rate_limit_buckets (endpoint, tokens, updated_at) VALUES ($1,$2,$3)", endpoint, tokens, now)
                    if tokens >= 1:
                        await conn.execute("UPDATE data_api_rate_limit_buckets SET tokens=$2, updated_at=$3 WHERE endpoint=$1", endpoint, tokens-1, now)
                        return
                    await conn.execute("UPDATE data_api_rate_limit_buckets SET tokens=$2, updated_at=$3 WHERE endpoint=$1", endpoint, tokens, now)
            await asyncio.sleep(max(0.01, (1-tokens)/rate))
