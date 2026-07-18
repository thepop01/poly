"""Execution seam. Phase 1 ships only DryRunBroker — no real orders are ever
sent. Real venue brokers exist as stubs that refuse until keys + an explicit
EXECUTION_MODE flip are provided (a later phase)."""
import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class NotConfiguredError(RuntimeError):
    """Raised when a live broker is used without credentials/arming."""


@dataclass
class OrderIntent:
    market_id: str
    token_id: str
    side: str            # 'BUY' | 'SELL'
    outcome: str         # 'YES' | 'NO'
    size_usdc: float
    limit_price: float | None = None


class ExecutionBroker(ABC):
    @abstractmethod
    def place_order(self, intent: OrderIntent) -> dict:
        ...


class DryRunBroker(ExecutionBroker):
    """Records intents, sends nothing. The only broker live in Phase 1."""
    def __init__(self) -> None:
        self.placed: list[OrderIntent] = []

    def place_order(self, intent: OrderIntent) -> dict:
        self.placed.append(intent)
        logger.info("DRY-RUN order (not sent): %s", intent)
        return {"status": "dry_run", "sent": False, "intent": intent.__dict__}


class PolymarketBroker(ExecutionBroker):
    """Stub. Refuses until CLOB creds + EXECUTION_MODE=live wired in a later phase."""
    def place_order(self, intent: OrderIntent) -> dict:
        raise NotConfiguredError("Polymarket live execution is not configured")


class KalshiBroker(ExecutionBroker):
    """Stub. Refuses until Kalshi trading keys + EXECUTION_MODE=live (later phase)."""
    def place_order(self, intent: OrderIntent) -> dict:
        raise NotConfiguredError("Kalshi live execution is not configured")


def get_broker(venue: str) -> ExecutionBroker:
    """Return the broker for a venue. Defaults to DryRunBroker unless
    EXECUTION_MODE=live (which is intentionally not honored in Phase 1)."""
    mode = os.getenv("EXECUTION_MODE", "dry_run")
    if mode != "live":
        return DryRunBroker()
    # EXECUTION_MODE=live is reserved for a later phase; still return the
    # venue stub so the refusal is explicit rather than a silent live order.
    if venue == "polymarket":
        return PolymarketBroker()
    if venue == "kalshi":
        return KalshiBroker()
    return DryRunBroker()
