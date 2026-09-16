import os
import httpx
import jwt
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from datetime import datetime, timedelta, timezone
from src.api.routers.auth import JWT_SECRET

router = APIRouter(prefix="/discord", tags=["discord"])

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
API_URL = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
DISCORD_REDIRECT_URI = f"{API_URL}/api/discord/callback"

@router.get("/login")
async def discord_login():
    """Redirect to Discord OAuth2 login."""
    if not DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Discord client ID not configured")
        
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20email"
    )
    return RedirectResponse(url)

@router.get("/callback")
async def discord_callback(request: Request, code: str):
    """Handle Discord OAuth2 callback."""
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Discord credentials not configured")

    async with httpx.AsyncClient() as client:
        # Exchange code for access token
        data = {
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        token_res = await client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to fetch token: {token_res.text}")
            
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token provided")

        # Get user info
        user_res = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
            
        user_info = user_res.json()
        discord_id = user_info.get("id")
        email = user_info.get("email") # Could be None if user has no email
        
        if not discord_id:
            raise HTTPException(status_code=400, detail="Could not get Discord ID")

    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")

    # Upsert user or find user
    async with pool.acquire() as conn:
        # Check if user exists by discord_id
        user = await conn.fetchrow("SELECT * FROM users WHERE discord_id = $1", discord_id)
        
        if not user and email:
            # Check by email in case they already signed up normally
            user = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
            if user:
                # Link discord account to existing user
                await conn.execute("UPDATE users SET discord_id = $1 WHERE user_id = $2", discord_id, user["user_id"])
        
        if not user:
            if not email:
                # If no email from discord, generate a placeholder
                email = f"{discord_id}@discord.local"
                
            # Create new user (password_hash is nullable after migration)
            row = await conn.fetchrow("""
                INSERT INTO users (email, discord_id)
                VALUES ($1, $2)
                RETURNING *
            """, email, discord_id)
            user_id = row["user_id"]
        else:
            user_id = user["user_id"]

    # Generate JWT
    secret = JWT_SECRET
    expire_minutes = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    expires_delta = timedelta(minutes=expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "discord_id": discord_id,
        "exp": expire
    }
    jwt_token = jwt.encode(to_encode, secret, algorithm="HS256")

    # Redirect to frontend with token in URL query param
    frontend_url = os.getenv("NEXT_PUBLIC_SITE_URL", "http://localhost:3000")
    return RedirectResponse(f"{frontend_url}/?token={jwt_token}")
