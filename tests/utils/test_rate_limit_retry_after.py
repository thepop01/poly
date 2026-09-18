import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.utils.polymarket_rate_limit import respect_retry_after

@pytest.mark.asyncio
async def test_sleeps_on_retry_after_header():
    response = MagicMock()
    response.status = 429
    response.headers = {"Retry-After": "2"}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(response)
    mock_sleep.assert_called_once_with(2.0)

@pytest.mark.asyncio
async def test_no_sleep_on_200():
    response = MagicMock()
    response.status = 200
    response.headers = {}
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await respect_retry_after(response)
    mock_sleep.assert_not_called()
