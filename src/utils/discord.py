import httpx
import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Webhook URLs can be set in environment variables
# e.g., DISCORD_DEPOSITS_WEBHOOK_URL=https://discord.com/api/webhooks/...
def get_webhook_url(channel: str) -> Optional[str]:
    env_var = f"DISCORD_{channel.upper()}_WEBHOOK_URL"
    return os.getenv(env_var)

async def send_discord_webhook(content: str, embeds: Optional[List[Dict[str, Any]]] = None, channel: str = "alerts") -> bool:
    """Send a message to a Discord webhook channel."""
    webhook_url = get_webhook_url(channel)
    if not webhook_url:
        logger.warning(f"No Discord webhook URL configured for channel: {channel}")
        return False
        
    payload: Dict[str, Any] = {"content": content}
    if embeds:
        payload["embeds"] = embeds
        
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                return True
            logger.error(f"Discord webhook failed: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Error sending Discord webhook: {e}")
        
    return False
