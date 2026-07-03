"""
Wallet Discovery Worker

Pulls wallets from the discovery queue and evaluates them against filters:
  - PnL (all-time, monthly, weekly) > $10,000
  - Volume (all-time, monthly, weekly) > $100,000

Runs on a schedule (every hour recommended).
"""

import asyncio
import asyncpg
import aiohttp
import os
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db")

# Thresholds
MIN_PNL = 10_000       # $10k profit
MIN_VOLUME = 100_000   # $100k volume
BATCH_SIZE = 100       # wallets to process per run (fast: no historical backfill)


def _parse(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


async def fetch_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch all positions for a wallet from Polymarket Data API with pagination."""
    all_positions = []
    offset = 0
    limit = 500
    
    while True:
        url = f"https://data-api.polymarket.com/positions?user={address}&limit={limit}&offset={offset}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data:
                        break
                    if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                        break
                    all_positions.extend(data)
                    if len(data) < limit:
                        break
                    offset += limit
                else:
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch positions for {address} at offset {offset}: {e}")
            break
            
    return all_positions


async def fetch_all_trades(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Fetch all historical trades for a wallet from Polymarket Data API (paginated).
    Uses both maker and taker params for complete coverage."""
    all_trades = []
    limit = 500
    max_offset = 10000
    
    for role in ("maker", "taker"):
        offset = 0
        while True:
            url = f"https://data-api.polymarket.com/trades?{role}={address}&limit={limit}&offset={offset}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if not data:
                            break
                        if not isinstance(data, list) or (len(data) > 0 and not isinstance(data[0], dict)):
                            break
                        all_trades.extend(data)
                        if len(data) < limit:
                            break
                        offset += limit
                        if offset > max_offset:
                            break
                    else:
                        break
            except Exception as e:
                logger.warning(f"Failed to fetch trades for {address} via {role} at offset {offset}: {e}")
                break
            
    return all_trades


async def fetch_balance(session: aiohttp.ClientSession, address: str) -> float:
    """Fetch exact portfolio balance from Alchemy."""
    from src.utils.alchemy_client import alchemy_get_token_balances, USDC_CONTRACT
    try:
        b = await alchemy_get_token_balances(session, address, [USDC_CONTRACT])
        if b and b.get("tokenBalances"):
            val = b["tokenBalances"][0].get("tokenBalance")
            if val and val != "0x":
                return int(val, 16) / 10**6
    except Exception as e:
        logger.warning(f"Failed to fetch balance for {address}: {e}")
    return 0.0


def calculate_stats(positions: list[dict], trades: list[dict], deposits: float, withdrawals: float, balance: float, now: datetime) -> dict:
    """Calculate all-time, monthly, and weekly stats from raw data."""
    weekly_cutoff = now - timedelta(days=7)
    monthly_cutoff = now - timedelta(days=30)

    total_pnl = 0.0
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    position_value = 0.0
    total_volume = 0.0
    pnl_weekly = 0.0
    pnl_monthly = 0.0
    volume_weekly = 0.0
    volume_monthly = 0.0
    winning_count = 0
    resolved_count = 0
    max_trade_size = 0.0
    
    # Process Trades for Volume and Max Trade Size
    for t in trades:
        size = _parse(t.get("size"))
        price = _parse(t.get("price"))
        usdc_vol = size * price
        
        total_volume += usdc_vol
        if usdc_vol > max_trade_size:
            max_trade_size = usdc_vol
            
        timestamp = t.get("timestamp")
        if timestamp:
            try:
                t_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                if t_date >= weekly_cutoff:
                    volume_weekly += usdc_vol
                if t_date >= monthly_cutoff:
                    volume_monthly += usdc_vol
            except Exception:
                pass

    # Unrealized PnL from open positions
    unrealized_pnl = 0.0
    total_bought_from_positions = 0.0

    for pos in positions:
        cash_pnl = _parse(pos.get("cashPnl"))
        total_bought_from_positions += _parse(pos.get("totalBought"))
        
        # If currentValue is > 0, it's open (unrealized)
        curr_val = _parse(pos.get("currentValue"))
        if curr_val > 0:
            unrealized_pnl += cash_pnl
            position_value += curr_val

        end_date_str = pos.get("endDate")
        pos_date = None
        if end_date_str:
            try:
                pos_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if pos_date.tzinfo is None:
                    pos_date = pos_date.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        if pos_date and pos_date >= weekly_cutoff:
            pnl_weekly += cash_pnl
        if pos_date and pos_date >= monthly_cutoff:
            pnl_monthly += cash_pnl

        is_resolved = bool(pos.get("percentRealizedPnl")) or cash_pnl != 0
        if is_resolved:
            resolved_count += 1
            if cash_pnl > 0:
                winning_count += 1

    # -------------------------------------------------------------
    # EXACT PNL CALCULATION (The Pro/Quick Fix)
    # Using pUSD Withdrawals + Current Balance - Deposits
    # -------------------------------------------------------------
    total_pnl = (withdrawals + balance) - deposits
    realized_pnl = total_pnl - unrealized_pnl
    
    # Fallback to totalBought if trade volume is truncated by the 10k trade limit
    if total_bought_from_positions > total_volume:
        total_volume = total_bought_from_positions

    win_rate = (winning_count / resolved_count) if resolved_count > 0 else 0.0
    roi_pct = (total_pnl / total_volume * 100) if total_volume > 0 else 0.0
    alpha_score = (win_rate * 100) + (total_pnl / 1_000)

    # Determine tier
    if total_pnl >= 100_000 or total_volume >= 1_000_000:
        tier = "Diamond"
    elif total_pnl >= 50_000 or total_volume >= 500_000:
        tier = "Platinum"
    elif total_pnl >= 10_000 or total_volume >= 100_000:
        tier = "Gold"
    else:
        tier = "Silver"

    return {
        "total_pnl": total_pnl,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "position_value": position_value,
        "total_volume": total_volume,
        "pnl_weekly": pnl_weekly,
        "pnl_monthly": pnl_monthly,
        "volume_weekly": volume_weekly,
        "volume_monthly": volume_monthly,
        "win_rate": win_rate,
        "roi_pct": roi_pct,
        "resolved_count": resolved_count,
        "winning_count": winning_count,
        "alpha_score": alpha_score,
        "tier": tier,
        "max_trade_size": max_trade_size,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "balance": balance
    }


def determine_sources(stats: dict) -> list[str]:
    """Return which discovery signals this wallet qualifies for."""
    sources = []
    if stats["total_pnl"] >= MIN_PNL:
        sources.append("pnl_alltime")
    if stats["pnl_monthly"] >= MIN_PNL:
        sources.append("pnl_monthly")
    if stats["pnl_weekly"] >= MIN_PNL:
        sources.append("pnl_weekly")
    return sources


async def process_batch(conn: asyncpg.Connection, session: aiohttp.ClientSession, wallets: list[dict]):
    """Process discovery queue: fetch balance + positions, promote immediately if qualified.
    No historical trade backfill — stats start at 0 and stats_refresher builds them up."""
    now = datetime.now(timezone.utc)

    for item in wallets:
        address = item["address"]
        queue_source = item["source"]
        
        # ── fast path: skip wallets already in tracked_wallets ──
        existing = await conn.fetchrow("SELECT 1 FROM tracked_wallets WHERE address = $1", address)
        if existing:
            await conn.execute("UPDATE wallet_discovery_queue SET processed = TRUE WHERE address = $1", address)
            continue

        try:
            positions = await fetch_positions(session, address)
            balance = await fetch_balance(session, address)
        except Exception as e:
            logger.warning(f"Error fetching data for wallet {address[:10]}...: {e}")
            positions = []
            balance = 0.0

        # Compute position_value from open positions
        position_value = 0.0
        for pos in (positions or []):
            curr_val = _parse(pos.get("currentValue"))
            if curr_val > 0:
                position_value += curr_val

        # ── decide promotion ──
        if balance >= 10000 or position_value >= 10000:
            added_reason = "Deposit" if queue_source and "Deposit" in queue_source else "Trade"
            logger.info(f"Promoting {address[:10]}... balance={balance:.0f} pos_val={position_value:.0f} source={queue_source}")

            await conn.execute("""
                INSERT INTO tracked_wallets (
                    address, discovery_source, total_pnl, realized_pnl, unrealized_pnl, total_volume,
                    pnl_weekly, pnl_monthly, volume_weekly, volume_monthly,
                    win_rate, roi_pct, resolved_count, winning_count, tier, alpha_score,
                    last_indexed, max_trade_size, balance, deposits, withdrawals, position_value,
                    start_balance, start_deposits, start_withdrawals, start_stats_at
                ) VALUES ($1, $2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'Silver', 0, NOW(), 0, $3, 0, 0, $4,
                         $3, 0, 0, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    position_value = EXCLUDED.position_value,
                    last_indexed = NOW()
            """, address, [queue_source] if queue_source else [], balance, position_value)

            await conn.execute("""
                INSERT INTO wallet_stats (
                    address, total_pnl, total_volume, win_rate, roi_pct,
                    resolved_count, winning_count, active_days,
                    avg_position_size, avg_hold_time_hours,
                    biggest_win, biggest_loss, unrealised_pnl,
                    tier, alpha_score, last_updated,
                    trades_2x, trades_1_5x, strategy, added_reason
                ) VALUES ($1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 'Silver', 0, NOW(), 0, 0, 'Unknown', $2)
                ON CONFLICT (address) DO NOTHING
            """, address, added_reason)
        else:
            logger.debug(f"Wallet {address[:10]}... below thresholds (balance={balance:.0f}, pos_val={position_value:.0f}), skipping.")

        await conn.execute("UPDATE wallet_discovery_queue SET processed = TRUE WHERE address = $1", address)


async def run_discovery(db_url: str = DB_URL):
    """Main entry point for the discovery worker."""
    logger.info("Starting wallet discovery worker...")
    conn = await asyncpg.connect(db_url)

    # Fetch unprocessed wallets from queue
    rows = await conn.fetch(
        "SELECT address, source FROM wallet_discovery_queue WHERE processed = FALSE ORDER BY spotted_at ASC LIMIT $1",
        BATCH_SIZE
    )
    wallets = [{"address": r["address"], "source": r["source"]} for r in rows]
    logger.info(f"Found {len(wallets)} wallets to evaluate.")

    if wallets:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            await process_batch(conn, session, wallets)

    await conn.close()
    logger.info("Discovery worker finished.")


async def main():
    """Infinite loop for the orchestrator."""
    import signal
    shutdown = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    logger.info("Starting Wallet Queue Processor (interval=60s)")
    while not shutdown.is_set():
        try:
            await run_discovery()
        except Exception:
            logger.exception("Error in wallet discovery queue processor")
        
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("Wallet Queue Processor shut down cleanly")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
