"""
Leaderboard Stats Worker

Computes PnL, ROI, win_rate, alpha_score for tracked wallets using ONLY
trades and positions that occurred AFTER the wallet was added to the leaderboard.
Stats start fresh from added_at - no historical backfill.

Uses the Polymarket Data API to fetch trades and positions, filters by
trade timestamp >= tracked_wallets.start_stats_at, then matches to resolved
positions to compute realized PnL.
"""

import asyncio
import asyncpg
import aiohttp
import os
import signal
import logging
from datetime import datetime, timedelta, timezone

from src.utils.alchemy_client import (
    fetch_usdc_deposits,
    fetch_usdc_withdrawals,
    alchemy_get_token_balances,
    USDC_CONTRACT,
)

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")
POLL_INTERVAL = 300  # 5 minutes

def _parse(val, default=0.0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    all_positions = []
    offset = 0
    limit = 500
    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
                if not data:
                    break
                if not isinstance(data, list):
                    break
                all_positions.extend(data)
                if len(data) < limit:
                    break
                offset += limit
        except Exception:
            break
    return all_positions


async def fetch_trades_after(session: aiohttp.ClientSession, address: str, cutoff: datetime) -> list[dict]:
    all_trades = []
    limit = 500
    for role in ("maker", "taker"):
        offset = 0
        while True:
            url = f"https://data-api.polymarket.com/trades?{role}={address}&limit={limit}&offset={offset}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if not data:
                        break
                    if not isinstance(data, list):
                        break
                    for t in data:
                        ts = t.get("timestamp")
                        if ts:
                            try:
                                trade_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                            except Exception:
                                trade_dt = datetime.now(timezone.utc)
                        else:
                            trade_dt = datetime.now(timezone.utc)
                        if trade_dt >= cutoff:
                            all_trades.append(t)
                        elif trade_dt < cutoff - timedelta(days=1):
                            return all_trades
                    if len(data) < limit:
                        break
                    offset += limit
                    if offset > 10000:
                        break
            except Exception:
                break
    return all_trades


def compute_stats(trades: list[dict], positions: list[dict], total_pnl: float, realized_pnl: float, unrealized_pnl: float, start_stats_at: datetime) -> dict:
    total_volume = 0.0
    max_trade_size = 0.0
    biggest_win = 0.0
    biggest_loss = 0.0
    resolved_count = 0
    winning_count = 0
    trades_2x = 0
    trades_1_5x = 0
    trade_dates: set[str] = set()
    for t in trades:
        size = _parse(t.get("size"))
        price = _parse(t.get("price"))
        usdc_vol = size * price
        total_volume += usdc_vol
        if usdc_vol > max_trade_size:
            max_trade_size = usdc_vol
        ts = t.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                trade_dates.add(dt.strftime("%Y-%m-%d"))
            except Exception:
                pass
    asset_ids = set()
    for t in trades:
        aid = t.get("asset_id") or t.get("asset")
        if aid:
            asset_ids.add(aid)
    for p in positions:
        pos_asset = p.get("asset") or p.get("asset_id")
        if pos_asset not in asset_ids:
            continue
        cash_pnl = _parse(p.get("cashPnl"))
        is_resolved = bool(_parse(p.get("percentRealizedPnl")) > 0 or cash_pnl != 0)
        if is_resolved:
            resolved_count += 1
            if cash_pnl > 0:
                winning_count += 1
            avg_size = _parse(p.get("totalBought")) / max(resolved_count, 1)
            if cash_pnl >= avg_size:
                trades_2x += 1
            if cash_pnl >= avg_size * 0.5:
                trades_1_5x += 1
            if cash_pnl > biggest_win:
                biggest_win = cash_pnl
            if cash_pnl < biggest_loss:
                biggest_loss = cash_pnl
    active_days = max(len(trade_dates), 1)
    win_rate = (winning_count / resolved_count) if resolved_count > 0 else 0.0
    roi_pct = (total_pnl / total_volume * 100) if total_volume > 0 else 0.0
    alpha_score = (win_rate * 50) + (trades_2x * 10) + (trades_1_5x * 5) + (total_pnl / 1000)
    if total_volume >= 1_000_000:
        tier = "Diamond"
    elif total_volume >= 500_000:
        tier = "Platinum"
    elif total_volume >= 100_000:
        tier = "Gold"
    elif total_volume >= 10_000:
        tier = "Silver"
    else:
        tier = "Bronze"
    return {
        "total_volume": total_volume,
        "total_pnl": total_pnl,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "win_rate": win_rate,
        "roi_pct": roi_pct,
        "resolved_count": resolved_count,
        "winning_count": winning_count,
        "max_trade_size": max_trade_size,
        "biggest_win": biggest_win,
        "biggest_loss": biggest_loss,
        "trades_2x": trades_2x,
        "trades_1_5x": trades_1_5x,
        "alpha_score": alpha_score,
        "tier": tier,
        "active_days": active_days,
    }


async def fetch_website_pnl(session: aiohttp.ClientSession, address: str) -> dict | None:
    """Fetch all-time PnL/volume/rank/username from Polymarket's public
    /v1/leaderboard endpoint — same numbers as shown on the website.
    One cheap request per wallet, no trade aggregation needed."""
    url = f"https://data-api.polymarket.com/v1/leaderboard?user={address}&category=OVERALL&timePeriod=ALL"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if not isinstance(data, list) or not data:
                return None
            item = data[0]
            raw_name = (item.get("userName") or "").strip()[:255]
            # If the username is an address (starts with 0x), treat as no username
            if raw_name.lower().startswith("0x") and len(raw_name) > 10:
                raw_name = ""
            return {
                "pnl": _parse(item.get("pnl")),
                "volume": _parse(item.get("vol")),
                "rank": int(item.get("rank") or 0),
                "username": raw_name,
            }
    except Exception:
        return None


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    try:
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception:
        pass
    return 0.0


async def process_wallet(conn: asyncpg.Connection, session: aiohttp.ClientSession, address: str):
    row = await conn.fetchrow(
        "SELECT added_at, start_stats_at, start_balance, start_deposits, start_withdrawals FROM tracked_wallets WHERE address = $1",
        address
    )
    if not row:
        return
    start_stats_at = row["start_stats_at"]
    if not start_stats_at:
        start_stats_at = row["added_at"] or datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE tracked_wallets SET start_stats_at = $1 WHERE address = $2",
            start_stats_at, address
        )
    trades = await fetch_trades_after(session, address, start_stats_at)
    positions = await fetch_positions(session, address)
    balance = await fetch_balance(session, address)
    website = await fetch_website_pnl(session, address)
    if website:
        await conn.execute("""
            UPDATE tracked_wallets SET
                website_pnl = $2, website_volume = $3,
                website_rank = $4, username = $5,
                website_pnl_updated_at = NOW()
            WHERE address = $1
        """, address, website["pnl"], website["volume"], website["rank"], website["username"])
    deposits = await fetch_usdc_deposits(session, address) or 0.0
    withdrawals = await fetch_usdc_withdrawals(session, address) or 0.0
    start_balance = float(row["start_balance"] or 0)
    start_deposits = float(row["start_deposits"] or 0)
    start_withdrawals = float(row["start_withdrawals"] or 0)
    if start_balance == 0 and start_deposits == 0 and start_withdrawals == 0:
        start_balance = balance
        start_deposits = deposits
        start_withdrawals = withdrawals
        await conn.execute("""
            UPDATE tracked_wallets SET
                start_balance = $1, start_deposits = $2, start_withdrawals = $3
            WHERE address = $4
        """, start_balance, start_deposits, start_withdrawals, address)
    position_value = 0.0
    unrealized_pnl = 0.0
    for pos in (positions or []):
        curr_val = _parse(pos.get("currentValue"))
        cash_pnl = _parse(pos.get("cashPnl"))
        if curr_val > 0:
            position_value += curr_val
            unrealized_pnl += cash_pnl
    realized_pnl = (balance - start_balance) + (withdrawals - start_withdrawals) - (deposits - start_deposits)
    total_pnl = realized_pnl + unrealized_pnl
    stats = compute_stats(trades, positions, total_pnl, realized_pnl, unrealized_pnl, start_stats_at)
    await conn.execute("""
        INSERT INTO wallet_stats (address, win_rate, roi_pct, resolved_count, winning_count,
            total_volume, total_pnl, unrealised_pnl, biggest_win, biggest_loss, tier,
            active_days, alpha_score, trades_2x, trades_1_5x, last_updated)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW())
        ON CONFLICT (address) DO UPDATE SET
            win_rate = EXCLUDED.win_rate,
            roi_pct = EXCLUDED.roi_pct,
            resolved_count = EXCLUDED.resolved_count,
            winning_count = EXCLUDED.winning_count,
            total_volume = EXCLUDED.total_volume,
            total_pnl = EXCLUDED.total_pnl,
            unrealised_pnl = EXCLUDED.unrealised_pnl,
            biggest_win = EXCLUDED.biggest_win,
            biggest_loss = EXCLUDED.biggest_loss,
            tier = EXCLUDED.tier,
            active_days = EXCLUDED.active_days,
            alpha_score = EXCLUDED.alpha_score,
            trades_2x = EXCLUDED.trades_2x,
            trades_1_5x = EXCLUDED.trades_1_5x,
            last_updated = EXCLUDED.last_updated
    """, address,
        stats["win_rate"], stats["roi_pct"], stats["resolved_count"], stats["winning_count"],
        stats["total_volume"], stats["total_pnl"], stats["unrealized_pnl"],
        stats["biggest_win"], stats["biggest_loss"], stats["tier"],
        stats["active_days"], stats["alpha_score"], stats["trades_2x"], stats["trades_1_5x"]
    )
    await conn.execute("""
        UPDATE tracked_wallets SET
            total_pnl = $2, realized_pnl = $3, unrealized_pnl = $4,
            total_volume = $5, win_rate = $6, roi_pct = $7,
            resolved_count = $8, winning_count = $9,
            max_trade_size = $10, tier = $11, alpha_score = $12,
            balance = $13, deposits = $14, withdrawals = $15,
            position_value = $16, last_indexed = NOW()
        WHERE address = $1
    """, address,
        stats["total_pnl"], stats["realized_pnl"], stats["unrealized_pnl"],
        stats["total_volume"], stats["win_rate"], stats["roi_pct"],
        stats["resolved_count"], stats["winning_count"],
        stats["max_trade_size"], stats["tier"], stats["alpha_score"],
        balance, deposits, withdrawals, position_value
    )
    logger.info(
        f"Leaderboard stats updated for {address[:10]}... | "
        f"vol=${stats['total_volume']:.0f} pnl=${stats['total_pnl']:.0f} "
        f"wr={stats['win_rate']*100:.0f}% roi={stats['roi_pct']:.1f}%"
    )


async def run_leaderboard_stats(db_url: str = DB_URL):
    logger.info("Starting Leaderboard Stats worker (interval=%ds)...", POLL_INTERVAL)
    try:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    except Exception as e:
        logger.error(f"Failed to create pool: {e}")
        return
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT address FROM tracked_wallets ORDER BY last_indexed ASC"
                )
                wallets = [r["address"] for r in rows]
                logger.info(f"Refreshing leaderboard stats for {len(wallets)} wallets...")
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                    for address in wallets:
                        try:
                            await process_wallet(conn, session, address)
                        except Exception as e:
                            logger.warning(f"Error processing {address[:10]}...: {e}")
                        await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Leaderboard stats error: {e}")
        await asyncio.sleep(POLL_INTERVAL)


async def main():
    shutdown = asyncio.Event()
    def _handler():
        logger.info("Shutdown signal received")
        shutdown.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler)
        except NotImplementedError:
            pass
    logger.info(f"Starting Leaderboard Stats worker (interval={POLL_INTERVAL}s)")
    while not shutdown.is_set():
        try:
            await run_leaderboard_stats()
        except Exception:
            logger.exception("Error in leaderboard stats loop")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass
    logger.info("Leaderboard Stats Worker shut down cleanly")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
