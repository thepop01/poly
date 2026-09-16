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
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address

from src.api.limiter import limiter
from src.api.routers.auth import get_current_user
from src.research.analytics import ResearchAnalytics
from src.research.contracts import PanelMutation
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


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspacePatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChatCreate(BaseModel):
    title: str = Field(default="New research", min_length=1, max_length=120)
    workspace_id: UUID | None = None


class ChatPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    is_archived: Optional[bool] = None


class PanelPatch(PanelMutation):
    pass


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


def _workspace_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise HTTPException(status_code=422, detail="workspace name must not be blank")
    return value


@router.post("/workspaces")
async def create_workspace(
    request: Request, body: WorkspaceCreate, user: dict = Depends(get_current_user)
):
    name = _workspace_name(body.name)
    try:
        workspace = await _repo(request).create_workspace(_uid(user), name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workspace.model_dump(mode="json")


@router.get("/workspaces")
async def list_workspaces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    workspaces = await _repo(request).list_workspaces(_uid(user), limit)
    return {"workspaces": [workspace.model_dump(mode="json") for workspace in workspaces]}


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: UUID, request: Request, user: dict = Depends(get_current_user)
):
    workspace = await _repo(request).get_workspace(_uid(user), workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace.model_dump(mode="json")


@router.patch("/workspaces/{workspace_id}")
async def patch_workspace(
    workspace_id: UUID,
    body: WorkspacePatch,
    request: Request,
    user: dict = Depends(get_current_user),
):
    name = _workspace_name(body.name)
    try:
        workspace = await _repo(request).rename_workspace(_uid(user), workspace_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace.model_dump(mode="json")


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: UUID, request: Request, user: dict = Depends(get_current_user)
):
    repo = _repo(request)
    owner_id = _uid(user)
    if await repo.get_workspace(owner_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    if not await repo.delete_workspace(owner_id, workspace_id):
        raise HTTPException(status_code=409, detail="workspace has chats")
    return {"deleted": str(workspace_id)}


@router.get("/workspaces/{workspace_id}/tabs")
async def list_workspace_tabs(
    workspace_id: UUID, request: Request, user: dict = Depends(get_current_user)
):
    tabs = await _repo(request).list_workspace_tabs(_uid(user), workspace_id)
    if tabs is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"tabs": [tab.model_dump(mode="json") for tab in tabs]}


@router.get("/workspaces/{workspace_id}/panels")
async def list_workspace_panels(
    workspace_id: UUID, request: Request, user: dict = Depends(get_current_user)
):
    panels = await _repo(request).list_workspace_panels(_uid(user), workspace_id)
    if panels is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"panels": [panel.model_dump(mode="json") for panel in panels]}


@router.post("/chats")
async def create_chat(request: Request, body: ChatCreate, user: dict = Depends(get_current_user)):
    try:
        chat = await _repo(request).create_chat(_uid(user), body.title, body.workspace_id)
    except ValueError as exc:
        # A supplied workspace must not reveal whether it belongs to another user.
        raise HTTPException(status_code=404, detail="workspace not found") from exc
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
        if chat is None:
            # Another request may have deleted the chat after the initial read.
            # Do not continue into the archive fallback with no typed snapshot.
            raise HTTPException(status_code=404, detail="chat not found")
    if body.is_archived is not None:
        chat_before_archive = chat
        chat = await repo.archive_chat(owner_id, chat_id, body.is_archived)
        if chat is None:
            # Empty chats are intentionally deleted when archived, but preserve
            # the normal typed response shape for compatibility with clients.
            chat = chat_before_archive.model_copy(
                update={
                    "is_archived": True,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
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
    panel = await _repo(request).update_panel(_uid(user), panel_id, body)
    if panel is None:
        raise HTTPException(status_code=404, detail="panel not found")
    return panel.model_dump(mode="json")


@router.get("/chats/{chat_id}/results")
async def list_results(
    chat_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    repo = _repo(request)
    if await repo.get_chat(_uid(user), chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    summaries = await repo.list_result_summaries(_uid(user), chat_id, limit)
    return {"results": [s.model_dump(mode="json") for s in summaries]}


@router.get("/chats/{chat_id}/positions")
async def list_positions(
    chat_id: UUID,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    repo = _repo(request)
    if await repo.get_chat(_uid(user), chat_id) is None:
        raise HTTPException(status_code=404, detail="chat not found")
    analytics = ResearchAnalytics(request.app.state.pool)
    positions = await analytics.list_positions(_uid(user), chat_id, offset, limit)
    return {"positions": positions, "offset": offset, "limit": limit}



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
