import re
from typing import Any, List
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
import logging
from src.api.routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/wallets/custom", tags=["custom-wallets"])

EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")

class CustomWalletEntry(BaseModel):
    address: str
    reason: str = ""

class CustomWalletsPayload(BaseModel):
    wallets: List[CustomWalletEntry]

@router.post("")
async def add_custom_wallets(
    request: Request,
    payload: CustomWalletsPayload,
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Add a list of custom wallets to the database."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    if not payload.wallets:
        return {"success": True, "inserted": 0, "message": "No wallets provided"}

    # Extract unique valid addresses
    valid_wallets = []
    seen = set()
    for w in payload.wallets:
        addr = w.address.strip().lower()
        if EVM_ADDRESS_RE.match(addr) and addr not in seen:
            valid_wallets.append((addr, w.reason.strip()))
            seen.add(addr)

    if not valid_wallets:
        return {"success": False, "inserted": 0, "message": "No valid EVM addresses found"}

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Insert into wallets_v2 (ON CONFLICT DO UPDATE if you want to overwrite reason/tier, but we just want DO NOTHING for now or update tier_reason if it was dead)
                # We'll do an upsert: if it exists, update tier to CURATED if it's not CURATED, and update reason.
                wallets_query = """
                    INSERT INTO wallets_v2 (address, tier, tier_reason)
                    VALUES ($1, 'NEW', 'custom wallet added')
                    ON CONFLICT (address) DO UPDATE 
                    SET tier_reason = CASE WHEN $2 != '' THEN $2 ELSE wallets_v2.tier_reason END
                """
                await conn.executemany(wallets_query, valid_wallets)

                # 2. Insert into wallet_sources_v2 as 'custom'
                sources_query = """
                    INSERT INTO wallet_sources_v2 (address, source, source_detail)
                    VALUES ($1, 'custom', $2)
                    ON CONFLICT (address, source) DO UPDATE
                    SET source_detail = CASE WHEN $2 != '' THEN $2 ELSE wallet_sources_v2.source_detail END
                """
                await conn.executemany(sources_query, valid_wallets)

        return {
            "success": True,
            "inserted": len(valid_wallets),
            "message": f"Successfully processed {len(valid_wallets)} custom wallets"
        }
    except Exception as e:
        logger.error(f"Error adding custom wallets: {e}")
        raise HTTPException(status_code=500, detail=str(e))
