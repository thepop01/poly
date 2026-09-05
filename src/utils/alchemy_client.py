"""
Alchemy API Client with automatic key rotation and exponential backoff.
"""
import os
import asyncio
import aiohttp
import logging
from itertools import cycle
from dotenv import load_dotenv

load_dotenv()

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
USDC_CONTRACT = "0x3c499c542cef6e924e22cab0d4c1ccec5e48cb12"  # Native USDC on Polygon
USDC_E_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e (Bridged)
PUSD_CONTRACT = os.environ.get("PUSD_CONTRACT", "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")  # pUSD (Polymarket deposit token)
CTF_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
COLLATERAL_ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee".lower()
COLLATERAL_OFFRAMP = "0x2957922Eb93258b93368531d39fAcCA3B4dC5854".lower()

# Eagerly load keys at import time
_keys: list[str] = _load_keys()
_key_cycle = cycle(_keys)

# Global semaphore to limit concurrent Alchemy requests across active keys
_alchemy_sem = asyncio.Semaphore(max(1, len(_keys)))



def get_next_key() -> str:
    return next(_key_cycle)


async def _request_with_backoff(
    session: aiohttp.ClientSession,
    method: str,
    params: list,
    max_retries: int = 2,   # was 5 — 2 retries per key fast-fails in ~3s vs 60-90s
    base_delay: float = 0.5,
) -> dict:
    """Make an Alchemy JSON-RPC request with exponential backoff on 429."""
    num_keys = max(1, len(_keys))
    total_attempts = max_retries * num_keys
    last_error = None

    async with _alchemy_sem:
        for attempt in range(total_attempts):
            api_key = get_next_key()
            url = f"{POLYGON_BASE}/{api_key}"
            payload = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }

            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "error" in data:
                            err_msg = str(data["error"])
                            if "429" in err_msg or "rate limit" in err_msg.lower():
                                delay = min(base_delay * (1.5 ** attempt), 5.0)
                                logger.debug(f"Alchemy 429 (response body), backing off {delay:.1f}s")
                                await asyncio.sleep(delay)
                                continue
                            raise RuntimeError(err_msg)
                        return data.get("result", {})
                    elif resp.status in (429, 502, 503, 504):
                        last_error = f"HTTP {resp.status} (rate-limited)"
                        delay = min(base_delay * (2.0 ** attempt), 30.0)  # up to 30s backoff
                        logger.warning(f"Alchemy {resp.status} on attempt {attempt+1}/{total_attempts}, backing off {delay:.1f}s")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        text = await resp.text()
                        logger.warning(f"Alchemy HTTP {resp.status}: {text}")
                        last_error = f"HTTP {resp.status}"
            except asyncio.TimeoutError:
                last_error = "timeout"
                await asyncio.sleep(0.5)
                continue
            except RuntimeError:
                raise
            except Exception as e:
                last_error = str(e)
                await asyncio.sleep(0.5)

        raise RuntimeError(f"All Alchemy keys exhausted or failed after {total_attempts} attempts (last: {last_error}).")


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
    from_block: int | str | None = None,
    to_block: int | str | None = None,
) -> dict:
    params: dict = {
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
    if from_block is not None:
        params["fromBlock"] = hex(from_block) if isinstance(from_block, int) else from_block
    if to_block is not None:
        params["toBlock"] = hex(to_block) if isinstance(to_block, int) else to_block

    return await _request_with_backoff(session, "alchemy_getAssetTransfers", [params])


async def alchemy_get_token_balances(session: aiohttp.ClientSession, address: str, contract_addresses: list[str]) -> dict:
    return await _request_with_backoff(session, "alchemy_getTokenBalances", [address, contract_addresses])


async def fetch_usdc_deposits(session: aiohttp.ClientSession, address: str) -> float | None:
    """
    Fetch total pUSD deposited INTO a wallet address on Polygon.
    We track this by summing pUSD minted from the zero address to the wallet.
    """
    total = 0.0
    page_key = None
    pages = 0

    try:
        while True:
            result = await alchemy_get_asset_transfers(
                session,
                from_address="0x0000000000000000000000000000000000000000",
                to_address=address,
                contract_addresses=[PUSD_CONTRACT],
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
        return None


async def fetch_usdc_withdrawals(session: aiohttp.ClientSession, address: str) -> float | None:
    """
    Fetch total pUSD withdrawn FROM a wallet address on Polygon.
    We track this by summing pUSD sent back to the pUSD contract for unwrap/burn.
    """
    total = 0.0
    page_key = None
    pages = 0

    try:
        while True:
            result = await alchemy_get_asset_transfers(
                session,
                from_address=address,
                to_address=PUSD_CONTRACT,
                contract_addresses=[PUSD_CONTRACT],
                max_count=255,
                page_key=page_key,
            )
            transfers = result.get("transfers", [])
            for t in transfers:
                total += t.get("value", 0) or 0

            pages += 1
            page_key = result.get("pageKey")
            if not page_key or pages > 5:
                break
        return total
    except Exception as e:
        logger.warning(f"Failed to fetch withdrawals for {address}: {e}")
        return None


EXCLUDED_EXCHANGE_ADDRESSES = {
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTF Exchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # CTF Exchange Settlement Proxy
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRisk Exchange
    "0xd91e80cf2e7be2e162c6513ce0608a65d39b7a1e",  # NegRisk Adapter
}


async def fetch_capital_metrics(
    session: aiohttp.ClientSession,
    address: str,
    from_block: int = 0,
    current_deposits: float = 0.0,
    current_withdrawals: float = 0.0,
    current_net_capital: float = 0.0,
    current_peak_capital: float = 0.0,
) -> tuple[float | None, float | None, float | None, float | None, int | None]:
    """
    Fetch total deposits, total withdrawals, peak capital, net capital, and max block seen for a wallet.
    Supports incremental fetching starting after `from_block`.
    Returns (total_deposits, total_withdrawals, peak_capital, net_capital, max_block_seen).
    """
    deposits_list = []
    withdrawals_list = []
    target_contracts = [PUSD_CONTRACT.lower(), USDC_CONTRACT.lower(), USDC_E_CONTRACT.lower()]
    addr_lower = address.lower()
    max_block_seen = from_block

    try:
        # 1. Fetch Incoming Deposits (pUSD mints & non-exchange transfers in)
        page_key = None
        pages = 0
        from_block_hex = hex(from_block) if from_block > 0 else None
        while True:
            res = await alchemy_get_asset_transfers(
                session,
                to_address=addr_lower,
                contract_addresses=target_contracts,
                max_count=255,
                page_key=page_key,
                from_block=from_block_hex,
            )
            for t in res.get("transfers", []):
                frm = (t.get("from") or "").lower()
                if frm in EXCLUDED_EXCHANGE_ADDRESSES:
                    continue  # Ignore trading proceeds / orderbook settlement payouts
                val = float(t.get("value") or 0)
                if val <= 0:
                    continue
                block = int(t.get("blockNum", "0x0"), 16) if isinstance(t.get("blockNum"), str) else t.get("blockNum", 0)
                if block > max_block_seen:
                    max_block_seen = block
                deposits_list.append({"block": block, "type": "deposit", "amount": val})
            
            pages += 1
            page_key = res.get("pageKey")
            if not page_key or pages >= 5:
                break

        # 2. Fetch Outgoing Withdrawals (Non-exchange transfers out to external wallets/bridges)
        page_key = None
        pages = 0
        while True:
            res = await alchemy_get_asset_transfers(
                session,
                from_address=addr_lower,
                contract_addresses=target_contracts,
                max_count=255,
                page_key=page_key,
                from_block=from_block_hex,
            )
            for t in res.get("transfers", []):
                to_a = (t.get("to") or "").lower()
                if to_a in EXCLUDED_EXCHANGE_ADDRESSES:
                    continue  # Ignore outgoing trade execution capital sent to exchange
                val = float(t.get("value") or 0)
                if val <= 0:
                    continue
                block = int(t.get("blockNum", "0x0"), 16) if isinstance(t.get("blockNum"), str) else t.get("blockNum", 0)
                if block > max_block_seen:
                    max_block_seen = block
                withdrawals_list.append({"block": block, "type": "withdrawal", "amount": val})
            
            pages += 1
            page_key = res.get("pageKey")
            if not page_key or pages >= 5:
                break
                
        # 3. Combine and calculate total deposits, withdrawals, and peak capital
        events = deposits_list + withdrawals_list
        events.sort(key=lambda x: x["block"])
        
        total_deposits = (current_deposits or 0.0) + sum(d["amount"] for d in deposits_list)
        total_withdrawals = (current_withdrawals or 0.0) + sum(w["amount"] for w in withdrawals_list)
        net_capital = current_net_capital or 0.0
        peak_capital = current_peak_capital or 0.0
        
        for event in events:
            if event["type"] == "deposit":
                net_capital += event["amount"]
                if net_capital > peak_capital:
                    peak_capital = net_capital
            elif event["type"] == "withdrawal":
                net_capital -= event["amount"]
                if net_capital < 0:
                    net_capital = 0.0
                
        return total_deposits, total_withdrawals, peak_capital, net_capital, max_block_seen
        
    except Exception as e:
        logger.warning(f"Failed to fetch capital metrics for {address}: {e}")
        return None, None, None, None, None

