"""Persistent streamed AI Research Hub chat API.

Every endpoint requires authentication; cross-owner IDs return 404 so one
account cannot probe another account's chats, results, runs, or panels.
Run output streams as newline-delimited JSON and always ends in exactly one
terminal event (``run.completed`` or ``run.failed``).
"""

import base64
import json
import logging
import os
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address

from src.api.limiter import limiter
from src.api.routers.auth import get_current_user
from src.research.analytics import ResearchAnalytics
from src.research.contracts import PanelState
from src.research.llm import build_provider_from_env
from src.research.orchestrator import ResearchOrchestrator
from src.research.repository import ResearchRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/research", tags=["research"])


def _uid(user: dict) -> str:
    return str(user["sub"])


def _repo(request: Request) -> ResearchRepository:
    return ResearchRepository(request.app.state.pool)


def _provider(request: Request) -> Any:
    factory = getattr(request.app.state, "research_provider_factory", None)
    if factory is not None:
        return factory()
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning(
            "research hub has no OPENAI_API_KEY configured; "
            "runs will fail with PROVIDER_NOT_CONFIGURED until one is set")
    return build_provider_from_env()


def _orchestrator(request: Request) -> ResearchOrchestrator:
    pool = request.app.state.pool
    return ResearchOrchestrator(
        ResearchRepository(pool), ResearchAnalytics(pool), _provider(request)
    )


class ChatCreate(BaseModel):
    title: str = Field(default="New research", min_length=1, max_length=120)


class ChatPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    is_archived: Optional[bool] = None


class PanelPatch(BaseModel):
    state: PanelState


class RunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


def _run_rate_key(request: Request) -> str:
    """Rate-limit run starts per authenticated user, falling back to IP."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = auth[7:].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
            if claims.get("sub"):
                return f"research-run:{claims['sub']}"
        except Exception:
            pass
    return f"research-run:{get_remote_address(request)}"


@router.post("/chats")
async def create_chat(request: Request, body: ChatCreate, user: dict = Depends(get_current_user)):
    chat = await _repo(request).create_chat(_uid(user), body.title)
    return chat.model_dump(mode="json")


@router.get("/chats")
async def list_chats(
    request: Request,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    chats = await _repo(request).list_chats(_uid(user), include_archived, limit)
    return {"chats": [c.model_dump(mode="json") for c in chats]}


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: UUID, request: Request, user: dict = Depends(get_current_user)):
    chat = await _repo(request).get_chat(_uid(user), chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat.model_dump(mode="json")


@router.patch("/chats/{chat_id}")
async def patch_chat(
    chat_id: UUID, body: ChatPatch, request: Request, user: dict = Depends(get_current_user)
):
    repo = _repo(request)
    owner_id = _uid(user)
    chat = await repo.get_chat(owner_id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if body.title is not None:
        chat = await repo.rename_chat(owner_id, chat_id, body.title)
    if body.is_archived is not None:
        chat = await repo.archive_chat(owner_id, chat_id, body.is_archived)
    assert chat is not None
    return chat.model_dump(mode="json")


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: UUID, request: Request, user: dict = Depends(get_current_user)):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            """DELETE FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid""",
            chat_id, _uid(user),
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="chat not found")
    return {"deleted": str(chat_id)}


@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: UUID,
    request: Request,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    repo = _repo(request)
    if await repo.get_chat(_uid(user), chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    messages = await repo.list_messages(_uid(user), chat_id, after_id, limit)
    return {"messages": [m.model_dump(mode="json") for m in messages]}


@router.get("/chats/{chat_id}/panels")
async def list_panels(chat_id: UUID, request: Request, user: dict = Depends(get_current_user)):
    repo = _repo(request)
    if await repo.get_chat(_uid(user), chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    panels = await repo.list_panels(_uid(user), chat_id)
    return {"panels": [p.model_dump(mode="json") for p in panels]}


@router.patch("/panels/{panel_id}")
async def patch_panel(
    panel_id: UUID, body: PanelPatch, request: Request, user: dict = Depends(get_current_user)
):
    panel = await _repo(request).update_panel_state(_uid(user), panel_id, body.state)
    if panel is None:
        raise HTTPException(status_code=404, detail="panel not found")
    return panel.model_dump(mode="json")


@router.get("/results/{result_set_id}")
async def get_result_page(
    result_set_id: UUID,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    repo = _repo(request)
    summary = await repo.get_result_summary(_uid(user), result_set_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="result set not found")
    members = await repo.page_result_members(_uid(user), result_set_id, offset, limit)
    assert members is not None
    return {"summary": summary.model_dump(mode="json"), "members": members}


@router.post("/chats/{chat_id}/runs")
@limiter.limit("10/minute", key_func=_run_rate_key)
async def start_run(
    chat_id: UUID, body: RunCreate, request: Request, user: dict = Depends(get_current_user)
):
    repo = _repo(request)
    owner_id = _uid(user)
    if await repo.get_chat(owner_id, chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if await repo.get_active_run(owner_id, chat_id) is not None:
        raise HTTPException(status_code=409, detail="a run is already active for this chat")
    orchestrator = _orchestrator(request)

    async def event_stream():
        async for event in orchestrator.run_stream(
            owner_id=owner_id, chat_id=chat_id, prompt=body.prompt, request=request
        ):
            yield json.dumps(event.model_dump(mode="json")) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
