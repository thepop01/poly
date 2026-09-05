import asyncio
import logging
import os
import sys
import time
import aiohttp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.workers.positions_winrate_backfill import process_wallet_backfill, WALLET_TIMEOUT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("hibernated_wallets_backfill")

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")
CONCURRENCY = 35


async def main():
    logger.info("=== ONE-TIME HIBERNATED WALLETS BACKFILL STARTED ===")
    from src.db import get_pool
    pool = await get_pool()
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY * 4,
        limit_per_host=30,
        keepalive_timeout=20,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=12, connect=4, sock_read=8),
    ) as session:
        total_processed = 0
        total_errors = 0
        # Livelock guard: wallets that repeatedly fail would be re-selected
        # forever (nothing advances their state on error). After N failures,
        # force-mark computed_at so they leave the queue.
        MAX_ATTEMPTS = 3
        failures: dict[str, int] = {}
        t_start = time.time()

        while True:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT w.address
                        FROM wallets_v2 w
                        LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
                        WHERE w.is_dormant = TRUE
                          AND w.tier != 'UNCLASSIFIED'
                          AND (m.computed_at IS NULL OR m.address IS NULL)
                        ORDER BY
                          CASE WHEN w.tier = 'CURATED' THEN 0 ELSE 1 END ASC,
                          w.last_trade_at DESC NULLS LAST
                        LIMIT 500
                    """)
                    wallets = [r["address"] for r in rows]
                    total = len(wallets)

                if total == 0:
                    logger.info(f"🎉 ONE-TIME HIBERNATED BACKFILL COMPLETE! Processed {total_processed:,} wallets with {total_errors:,} errors in {(time.time() - t_start)/60:.1f} minutes.")
                    break

                done, errors, force_marked = 0, 0, 0
                t0 = time.time()

                async def _process_one(addr):
                    nonlocal done, errors, force_marked
                    async with sem:
                        try:
                            async with pool.acquire() as conn:
                                await asyncio.wait_for(
                                    process_wallet_backfill(conn, session, addr),
                                    timeout=WALLET_TIMEOUT,
                                )
                            done += 1
                            failures.pop(addr, None)
                        except asyncio.TimeoutError as e:
                            errors += 1
                            failures[addr] = failures.get(addr, 0) + 1
                            logger.warning(f"Timeout {addr[:12]}... (attempt {failures[addr]}/{MAX_ATTEMPTS}): {e}")
                        except Exception as e:
                            errors += 1
                            failures[addr] = failures.get(addr, 0) + 1
                            logger.warning(f"Error {addr[:12]}... (attempt {failures[addr]}/{MAX_ATTEMPTS}): {e}")

                        if failures.get(addr, 0) >= MAX_ATTEMPTS:
                            # Force-mark so the queue advances; reset later by
                            # nulling wallet_metrics_v2.computed_at if desired.
                            try:
                                async with pool.acquire() as conn2:
                                    await conn2.execute("""
                                        INSERT INTO wallet_metrics_v2 (address, computed_at)
                                        VALUES ($1, NOW())
                                        ON CONFLICT (address) DO UPDATE SET computed_at = NOW()
                                    """, addr)
                                force_marked += 1
                                failures.pop(addr, None)
                                logger.warning(f"Force-marked {addr[:12]}... as computed after {MAX_ATTEMPTS} failed attempts")
                            except Exception as e:
                                logger.warning(f"Failed to force-mark {addr[:12]}...: {e}")

                        if (done + errors) % 50 == 0 or (done + errors) == total:
                            rate = (done + errors) / max(0.1, time.time() - t0)
                            logger.info(f"[Hibernated] Progress: {done+errors}/{total} (ok={done} err={errors}) | Speed: {rate:.1f} wallets/s")

                await asyncio.gather(*[_process_one(addr) for addr in wallets], return_exceptions=True)
                total_processed += done
                total_errors += errors
                if force_marked:
                    logger.warning(f"Batch force-marked {force_marked} repeatedly-failing wallets")
                logger.info(f"=== HIBERNATED BATCH COMPLETE: {done} ok, {errors} errors | Cumulative: {total_processed:,} done ===")
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
