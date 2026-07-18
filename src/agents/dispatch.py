"""Execute an agent's actions after its rule tree fires."""
import logging
from typing import Any, Mapping, Sequence

from src.agents.execution import OrderIntent, get_broker

logger = logging.getLogger(__name__)


async def dispatch_actions(
    conn: Any,
    agent: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    market: Mapping[str, Any],
    summary: str,
) -> list[dict]:
    receipts: list[dict] = []
    for action in actions:
        atype = action["action_type"]
        params = action.get("params") or {}
        if atype == "notify":
            msg = params.get("message") or f"{agent['name']}: {market.get('title')}"
            await conn.execute(
                """INSERT INTO notifications (user_id, agent_id, title, body)
                   VALUES ($1, $2, $3, $4)""",
                agent["owner_id"], agent["agent_id"],
                f"Agent fired: {agent['name']}", f"{msg}\n[{summary}]",
            )
            receipts.append({"action_type": "notify", "status": "sent"})
        elif atype == "trade":
            if not agent.get("trading_armed"):
                logger.warning("Agent %s trade skipped: not armed", agent["agent_id"])
                receipts.append({"action_type": "trade", "status": "skipped_disarmed"})
                continue
            intent = OrderIntent(
                market_id=params["market_id"],
                token_id=params["token_id"],
                side=params["side"],
                outcome=params["outcome"],
                size_usdc=float(params["size_usdc"]),
                limit_price=params.get("limit_price"),
            )
            broker = get_broker(params.get("venue", "polymarket"))
            receipt = broker.place_order(intent)
            receipt["action_type"] = "trade"
            receipts.append(receipt)
        else:
            logger.warning("Unknown action_type %r on agent %s", atype, agent["agent_id"])
            receipts.append({"action_type": atype, "status": "unknown"})
    return receipts
