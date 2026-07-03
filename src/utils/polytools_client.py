import aiohttp
import logging
from aiohttp import ClientTimeout

logger = logging.getLogger(__name__)

async def fetch_polytools_positions(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """
    Fetch all positions from activity.polymarket-tools.com.
    Returns the list of positions, each containing cashPnl, realizedPnl, totalBought, etc.
    """
    url = "https://activity.polymarket-tools.com/api/positions"
    payload = {"wallets": [address]}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with session.post(url, json=payload, headers=headers, timeout=ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("positions", [])
            else:
                logger.warning(f"Polytools API returned {resp.status} for {address}")
    except Exception as e:
        logger.warning(f"Failed to fetch Polytools positions for {address}: {e}")

    return []

async def fetch_polytools_balance(session: aiohttp.ClientSession, address: str) -> float:
    """
    Fetch balance from activity.polymarket-tools.com.
    """
    url = "https://activity.polymarket-tools.com/api/balance"
    payload = {"wallets": [address]}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with session.post(url, json=payload, headers=headers, timeout=ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("balance", 0.0))
    except Exception as e:
        logger.warning(f"Failed to fetch Polytools balance for {address}: {e}")

    return 0.0

