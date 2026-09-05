"""FastAPI initialization and lifespan management. Database accounting active v2."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()

from src.db import get_pool, close_pool, init_db
from src.api.routers import trades, ws, leaderboard, wallets, watchlist, alpha_calls, tracker, discord, auth, tracked_wallets
from src.api.routers import leaderboard_v2, wallets_v2, alpha_calls_v2, tracked_wallets_v2, trades_v2, custom_wallets, agents, notifications, research
import asyncio
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from src.api.limiter import limiter

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import asyncpg
from src.api.errors import AppError

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI application."""
    # Initialize the database connection pool
    logger.info("Starting up FastAPI - initializing db pool")
    app.state.pool = await get_pool()
    await init_db(app.state.pool)
    app.state.ws_task = asyncio.create_task(ws.start_db_poll_broadcaster(app.state.pool))
    
    yield
    # Close the pool
    logger.info("Shutting down FastAPI - closing db pool")
    app.state.ws_task.cancel()
    await close_pool()

app = FastAPI(
    title="Polymarket Analytics API",
    description="Backend API for Polymarket Dashboard MVP",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore

import os

raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global Exception Handlers ---

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": exc.detail, "details": None}}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(map(str, error["loc"])), "issue": error["msg"]} for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Invalid input provided.", "details": details}}
    )

@app.exception_handler(asyncpg.exceptions.PostgresError)
async def postgres_error_handler(request: Request, exc: asyncpg.exceptions.PostgresError):
    logger.error(f"Database Error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "DATABASE_ERROR", "message": "A database operation failed.", "details": None}}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred.", "details": None}}
    )

app.include_router(auth.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
app.include_router(trades.router, prefix="/api")
app.include_router(leaderboard.router, prefix="/api")
app.include_router(wallets.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(alpha_calls.router, prefix="/api")
app.include_router(tracker.router, prefix="/api")
app.include_router(discord.router, prefix="/api")
app.include_router(tracked_wallets.router, prefix="/api")

# Mount V2 routers
app.include_router(leaderboard_v2.router, prefix="/api")
app.include_router(wallets_v2.router, prefix="/api")
app.include_router(alpha_calls_v2.router, prefix="/api")
app.include_router(tracked_wallets_v2.router, prefix="/api")
app.include_router(trades_v2.router, prefix="/api")
app.include_router(custom_wallets.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(research.router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)

