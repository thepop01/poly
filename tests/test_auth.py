import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_signup_success(async_client: AsyncClient):
    """Test successful user signup."""
    # Use a unique email to avoid conflicts across test runs
    import time
    test_email = f"newuser_{int(time.time())}@example.com"
    
    response = await async_client.post("/api/auth/signup", json={
        "email": test_email,
        "password": "securepassword123",
        "wallet_address": "0x1234567890abcdef"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "user_id" in data
    assert data["message"] == "User created successfully"

@pytest.mark.asyncio
async def test_signup_duplicate_email(async_client: AsyncClient):
    """Test signing up with an already registered email."""
    # This email is seeded by the auth_client fixture in conftest.py
    test_email = "integration_test@example.com"
    
    response = await async_client.post("/api/auth/signup", json={
        "email": test_email,
        "password": "securepassword123"
    })
    
    # Should hit our custom ConflictError global handler
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "CONFLICT"
    assert data["error"]["message"] == "Email already registered"

@pytest.mark.asyncio
async def test_login_success(async_client: AsyncClient):
    """Test login to get JWT tokens."""
    # Setup: Create the user
    import time
    test_email = f"login_{int(time.time())}@example.com"
    password = "testpassword123"
    
    await async_client.post("/api/auth/signup", json={
        "email": test_email,
        "password": password
    })
    
    # Test Login
    response = await async_client.post("/api/auth/login", json={
        "email": test_email,
        "password": password
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_login_invalid_credentials(async_client: AsyncClient):
    """Test login with bad password."""
    response = await async_client.post("/api/auth/login", json={
        "email": "integration_test@example.com",
        "password": "wrongpassword!"
    })
    
    # Should hit our AuthError global handler
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
