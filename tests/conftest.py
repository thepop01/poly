import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os
import asyncpg
from typing import AsyncGenerator
from src.api.main import app
from src.api.routers.auth import create_access_token

# Configure pytest-asyncio to use asyncio event loop for all tests
@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture(scope="session")
async def test_pool():
    """Create a database connection pool for the test session."""
    # Tests assume a local development database 'poly_db'
    db_url = os.getenv("DATABASE_URL", "postgres://poly_user:poly_password@localhost:5432/poly_db")
    pool = await asyncpg.create_pool(db_url)
    
    # Optional: We could run `init_db(pool)` here if we want to ensure tables exist,
    # but the app lifespan usually handles that.
    
    yield pool
    await pool.close()

@pytest_asyncio.fixture(scope="function")
async def async_client(test_pool) -> AsyncGenerator[AsyncClient, None]:
    """Provides a pre-configured AsyncClient that routes to our FastAPI app."""
    # Override the app's pool state with our test pool
    app.state.pool = test_pool
    
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as client:
        yield client

@pytest_asyncio.fixture(scope="function")
async def auth_client(async_client, test_pool) -> AsyncClient:
    """Provides an AsyncClient pre-authenticated with a test user."""
    # Create a mock user in the DB
    test_email = "integration_test@example.com"
    test_password_hash = "mock_hash" # Doesn't matter since we bypass login
    
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash) VALUES ($1, $2) ON CONFLICT (email) DO UPDATE SET password_hash = $2 RETURNING user_id",
            test_email, test_password_hash
        )
        user_id = row["user_id"]
        
    # Generate a valid JWT
    token = create_access_token(str(user_id), test_email)
    
    # Inject it into the client headers
    async_client.headers.update({"Authorization": f"Bearer {token}"})
    return async_client
