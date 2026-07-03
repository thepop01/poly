from fastapi import APIRouter, Depends, Request, HTTPException
from src.api.errors import AuthError, ConflictError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import os
import secrets

# Load JWT secret once at module level â€” crash early if missing
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is required. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class SignupRequest(BaseModel):
    email: str
    password: str
    wallet_address: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

def create_access_token(user_id: str, email: str, expires_delta: timedelta = timedelta(minutes=15)):
    to_encode = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + expires_delta}
    return jwt.encode(to_encode, JWT_SECRET, algorithm="HS256")

def create_refresh_token():
    return secrets.token_hex(32)

@router.post("/signup")
async def signup(request: Request, body: SignupRequest):
    pool = request.app.state.pool
    hashed_password = pwd_context.hash(body.password)
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id FROM users WHERE email = $1", body.email)
        if existing:
            raise ConflictError("Email already registered")
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash, wallet_address) VALUES ($1, $2, $3) RETURNING user_id",
            body.email, hashed_password, body.wallet_address
        )
        return {"user_id": str(row["user_id"]), "message": "User created successfully"}

@router.post("/login")
async def login(request: Request, body: LoginRequest):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT user_id, email, password_hash, discord_id FROM users WHERE email = $1", body.email
        )
        if not user:
            raise AuthError("Invalid email or password")
        if user["discord_id"] and not user["password_hash"]:
            raise AuthError(
                "This account uses Discord sign-in. Please log in via Discord."
            )
        if not user["password_hash"] or not pwd_context.verify(body.password, user["password_hash"]):
            raise AuthError("Invalid email or password")
            
        access_token = create_access_token(str(user["user_id"]), user["email"])
        refresh_token = create_refresh_token()
        
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        await conn.execute(
            "INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES ($1, $2, $3)",
            refresh_token, user["user_id"], expires_at
        )
        
        return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}

@router.post("/refresh")
async def refresh(request: Request, body: RefreshRequest):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT u.user_id, u.email, rt.expires_at, rt.revoked 
               FROM refresh_tokens rt 
               JOIN users u ON rt.user_id = u.user_id 
               WHERE rt.token = $1""", 
            body.refresh_token
        )
        
        if not row:
            raise AuthError("Invalid refresh token")
            
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if row["revoked"] or expires_at < datetime.now(timezone.utc):
            raise AuthError("Refresh token expired or revoked")
            
        access_token = create_access_token(str(row["user_id"]), row["email"])
        return {"access_token": access_token, "token_type": "bearer"}

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Extract user from JWT token."""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception:
        raise AuthError("Invalid token")

async def require_admin(
    request: Request,
    user: dict = Depends(get_current_user)
) -> dict:
    """Require admin privileges â€” checks DB for current admin status."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_admin FROM users WHERE user_id = $1::uuid", user["sub"]
        )
        if not row or not row["is_admin"]:
            raise HTTPException(status_code=403, detail="Admin access required")
    return user

