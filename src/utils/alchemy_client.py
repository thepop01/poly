"""
Alchemy API Client with automatic key rotation.
"""
import os
import asyncio
import aiohttp
import logging
from itertools import cycle

logger = logging.getLogger(__name__)


def _load_keys() -> list[str]:
    keys = []
    i = 1
    while True:
        key = os.environ.get(f"ALCHEMY_API_KEY_{i}")
        if not key or key.startswith("your_"):
            break
        keys.append(key)
        i += 1
    if not keys:
        single = os.environ.get("ALCHEMY_API_KEY")
        if single and not single.startswith("your_"):
            keys.append(single)
    if not keys:
        logger.warning("No valid ALCHEMY_API_KEY found.")
        keys = ["demo"]
    return keys


POLYGON_BASE = "https://polygon-mainnet.g.alchemy.com/v2"

# Polymarket V2 Architecture (Post April 2026)
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e Token
CTF_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
COLLATERAL_ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee".lower()
COLLATERAL_OFFRAMP = "0x2957922Eb93258b93368531d39fAcCA3B4dC5854".lower()

_keys: list[str] = []
_key_cycle = None


def get_next_key() -> str:
    global _keys, _key_cycle
    if not _keys:
        _keys = _load_keys()
        _key_cycle = cycle(_keys)
    return next(_key_cycle)


async def alchemy_get_asset_transfers(
    session: aiohttp.ClientSession,
    from_address: str | None = None,
    to_address: str | None = None,
    contract_addresses: list[str] | None = None,
    max_count: int = 1000,
    page_key: str | None = None,
    order: str = "asc",
    category: list[str] = ["erc20"],
    with_metadata: bool = False,
) -> dict:
    for attempt in range(len(_keys) + 1):
        api_key = get_next_key()
        url = f"{POLYGON_BASE}/{api_key}"

        params = {
            "category": category,
            "maxCount": hex(max_count),
            "order": order,
            "withMetadata": with_metadata,
        }
        if from_address:
            params["fromAddress"] = from_address.lower()
        if to_address:
            params["toAddress"] = to_address.lower()
        if contract_addresses:
            params["contractAddresses"] = [c.lower() for c in contract_addresses]
        if page_key:
            params["pageKey"] = page_key

        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getAssetTransfers",
            "params": [params],
        }

        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "error" in data:
                        err_msg = str(data["error"])
                        if "429" in err_msg or "rate limit" in err_msg.lower():
                            continue
                        logger.error(f"Alchemy API Error: {err_msg}")
                        raise RuntimeError(err_msg)
                    return data.get("result", {})
                elif resp.status == 429:
                    continue
                else:
                    text = await resp.text()
                    logger.warning(f"Alchemy HTTP {resp.status}: {text}")
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.warning(f"Alchemy request failed: {e}")
            continue

    raise RuntimeError("All Alchemy keys exhausted or failed.")


async def alchemy_get_token_balances(session: aiohttp.ClientSession, address: str, contract_addresses: list[str]) -> dict:
    for attempt in range(len(_keys) + 1):
        api_key = get_next_key()
        url = f"{POLYGON_BASE}/{api_key}"
        payload = {
            "id": 1,
            "jsonrpc": "2.0",
            "method": "alchemy_getTokenBalances",
            "params": [address, contract_addresses],
        }
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "error" in data:
                        err_msg = str(data["error"])
                        if "429" in err_msg or "rate limit" in err_msg.lower():
                            continue
                        raise RuntimeError(err_msg)
                    return data.get("result", {})
                elif resp.status == 429:
                    continue
        except Exception:
            continue
    return {}


async def fetch_usdc_deposits(session: aiohttp.ClientSession, address: str) -> float | None:
    """
    Fetch total pUSD deposited INTO a wallet address on Polygon.
    We track this by calculating the total pUSD received directly from the CollateralOnramp contract.
    """
    total = 0.0
    page_key = None
    pages = 0

    try:
        while True:
            result = await alchemy_get_asset_transfers(
                session,
                from_address=address,
                to_address=COLLATERAL_ONRAMP,
                contract_addresses=[USDC_CONTRACT],
                max_count=255,
                page_key=page_key,
            )
            transfers = result.get("transfers", [])
            for t in transfers:
                total += t.get("value", 0) or 0

            pages += 1
            page_key = result.get("pageKey")
            if not page_key or pages > 10:
                break
        return total
    except Exception as e:
        logger.warning(f"Failed to fetch deposits for {address}: {e}")
        return 0.0


async def fetch_usdc_withdrawals(session: aiohttp.ClientSession, address: str) -> float | None:
    """
    Fetch total pUSD withdrawn FROM a wallet address on Polygon.
    We track this by calculating the total pUSD sent directly to the CollateralOfframp contract.
    """
    total = 0.0
    page_key = None
    pages = 0

    try:
        while True:
            result = await alchemy_get_asset_transfers(
                session,
                from_address=address,
                to_address=COLLATERAL_OFFRAMP,
                contract_addresses=[USDC_CONTRACT],
                max_count=255,
                page_key=page_key,
            )
            transfers = result.get("transfers", [])
            for t in transfers:
                total += t.get("value", 0) or 0

            pages += 1
            page_key = result.get("pageKey")
            if not page_key or pages > 10:
                break
        return total
    except Exception as e:
        logger.warning(f"Failed to fetch withdrawals for {address}: {e}")
        return 0.0



