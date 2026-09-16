"""Owner-scoped persistence for the AI Research Hub workspace.

Every public method accepts ``owner_id``; child-row operations join through
``research_chats`` rather than trusting only a child UUID. No SQL is built by
interpolating owner IDs, entity keys, titles, or filters.
"""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import UUID

from src.research.contracts import (
    PanelMutation,
    PanelState,
    ResearchChat,
    ResearchMessage,
    ResearchPanel,
    ResearchRun,
    ResearchWorkspace,
    ResearchWorkspaceTab,
    ResultSetSummary,
    RunStatus,
    WorkspaceTabType,
)


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if value is not None else {}


def _row_model(model_cls: Any, row: Any) -> Any:
    data = dict(row)
    for key in ("metadata", "definition", "summary", "layout", "config"):
        if key in data:
            data[key] = _json(data[key])
    return model_cls.model_validate(data)


_WORKSPACE_TABS = (
    (WorkspaceTabType.WALLET_GROUPS.value, "Wallet Groups"),
    (WorkspaceTabType.MARKET_GROUPS.value, "Market Groups"),
    (WorkspaceTabType.AGENTS.value, "Agents"),
)


def _workspace_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("workspace name must not be blank")
    if len(value) > 120:
        raise ValueError("workspace name must be at most 120 characters")
    return value


class ResearchRepository:
    def __init__(self, pool: Any):
        self.pool = pool

    # -- workspaces ----------------------------------------------------

    async def create_workspace(self, owner_id: str, name: str) -> ResearchWorkspace:
        name = _workspace_name(name)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO research_workspaces (owner_id, name)
                       VALUES ($1::uuid, $2)
                       RETURNING workspace_id, name, created_at, updated_at""",
                    owner_id, name,
                )
                await conn.executemany(
                    """INSERT INTO research_workspace_tabs (workspace_id, tab_type, label)
                       VALUES ($1, $2, $3)""",
                    [(row["workspace_id"], tab_type, label) for tab_type, label in _WORKSPACE_TABS],
                )
        return ResearchWorkspace.model_validate(dict(row))

    async def list_workspaces(self, owner_id: str, limit: int = 50) -> list[ResearchWorkspace]:
        limit = max(1, min(limit, 100))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT workspace_id, name, created_at, updated_at
                   FROM research_workspaces WHERE owner_id = $1::uuid
                   ORDER BY updated_at DESC, created_at ASC LIMIT $2""", owner_id, limit,
            )
        return [ResearchWorkspace.model_validate(dict(row)) for row in rows]

    async def get_workspace(self, owner_id: str, workspace_id: UUID) -> ResearchWorkspace | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT workspace_id, name, created_at, updated_at
                   FROM research_workspaces
                   WHERE workspace_id = $1 AND owner_id = $2::uuid""", workspace_id, owner_id,
            )
        return ResearchWorkspace.model_validate(dict(row)) if row else None

    async def rename_workspace(self, owner_id: str, workspace_id: UUID, name: str) -> ResearchWorkspace | None:
        name = _workspace_name(name)
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE research_workspaces SET name = $3, updated_at = NOW()
                   WHERE workspace_id = $1 AND owner_id = $2::uuid
                   RETURNING workspace_id, name, created_at, updated_at""",
                workspace_id, owner_id, name,
            )
        return ResearchWorkspace.model_validate(dict(row)) if row else None

    async def delete_workspace(self, owner_id: str, workspace_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """SELECT w.workspace_id FROM research_workspaces w
                       WHERE w.workspace_id = $1 AND w.owner_id = $2::uuid
                       FOR UPDATE""", workspace_id, owner_id,
                )
                if not row:
                    return False
                if await conn.fetchval(
                    "SELECT 1 FROM research_chats WHERE workspace_id = $1 LIMIT 1", workspace_id
                ):
                    return False
                deleted = await conn.execute(
                    "DELETE FROM research_workspaces WHERE workspace_id = $1", workspace_id
                )
        return deleted == "DELETE 1"

    async def list_workspace_tabs(self, owner_id: str, workspace_id: UUID) -> list[ResearchWorkspaceTab] | None:
        async with self.pool.acquire() as conn:
            owned = await conn.fetchval(
                "SELECT 1 FROM research_workspaces WHERE workspace_id = $1 AND owner_id = $2::uuid",
                workspace_id, owner_id,
            )
            if not owned:
                return None
            rows = await conn.fetch(
                """SELECT t.workspace_tab_id, t.workspace_id, t.tab_type, t.label, t.created_at
                   FROM research_workspace_tabs t
                   WHERE t.workspace_id = $1
                   ORDER BY CASE t.tab_type
                     WHEN 'wallet_groups' THEN 1 WHEN 'market_groups' THEN 2 WHEN 'agents' THEN 3 END""",
                workspace_id,
            )
        return [_row_model(ResearchWorkspaceTab, row) for row in rows]

    # -- chats ---------------------------------------------------------

    async def create_chat(
        self, owner_id: str, title: str = "New research", workspace_id: UUID | None = None
    ) -> ResearchChat:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if workspace_id is None:
                    # Serialize default-workspace selection/creation per owner so
                    # concurrent first chats cannot create duplicate canvases.
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                        owner_id,
                    )
                if workspace_id is not None:
                    # Serialize workspace-owned chat creation with workspace
                    # deletion. If deletion wins, this returns no row and the
                    # route can deterministically translate the ownership miss
                    # to a non-disclosing 404 instead of leaking an FK error.
                    owns = await conn.fetchval(
                        """SELECT workspace_id FROM research_workspaces
                           WHERE workspace_id = $1 AND owner_id = $2::uuid
                           FOR UPDATE""",
                        workspace_id, owner_id,
                    )
                    if not owns:
                        raise ValueError("workspace does not belong to owner")
                else:
                    workspace_id = await conn.fetchval(
                        """SELECT workspace_id FROM research_workspaces
                           WHERE owner_id = $1::uuid ORDER BY created_at ASC LIMIT 1
                           FOR UPDATE""", owner_id,
                    )
                    if workspace_id is None:
                        row = await conn.fetchrow(
                            """INSERT INTO research_workspaces (owner_id, name)
                               VALUES ($1::uuid, 'New research')
                               RETURNING workspace_id""", owner_id,
                        )
                        workspace_id = row["workspace_id"]
                        await conn.executemany(
                            """INSERT INTO research_workspace_tabs (workspace_id, tab_type, label)
                               VALUES ($1, $2, $3)""",
                            [(workspace_id, tab_type, label) for tab_type, label in _WORKSPACE_TABS],
                        )
                row = await conn.fetchrow(
                    """INSERT INTO research_chats (owner_id, workspace_id, title)
                       VALUES ($1::uuid, $2, $3)
                       RETURNING chat_id, workspace_id, title, is_archived, created_at, updated_at""",
                    owner_id, workspace_id, title,
                )
        return ResearchChat.model_validate(dict(row))

    async def list_chats(
        self, owner_id: str, include_archived: bool = False, limit: int = 50
    ) -> list[ResearchChat]:
        limit = max(1, min(limit, 100))
        async with self.pool.acquire() as conn:
            if include_archived:
                rows = await conn.fetch(
                    """SELECT c.chat_id, c.workspace_id, c.title, c.is_archived, c.created_at, c.updated_at
                       FROM research_chats c
                       WHERE c.owner_id = $1::uuid
                         AND (c.is_archived = FALSE OR EXISTS (
                             SELECT 1 FROM research_messages m WHERE m.chat_id = c.chat_id
                         ))
                       ORDER BY c.updated_at DESC LIMIT $2""",
                    owner_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT chat_id, workspace_id, title, is_archived, created_at, updated_at
                       FROM research_chats WHERE owner_id = $1::uuid AND is_archived = FALSE
                       ORDER BY updated_at DESC LIMIT $2""",
                    owner_id, limit,
                )
        return [ResearchChat.model_validate(dict(r)) for r in rows]

    async def get_chat(self, owner_id: str, chat_id: UUID) -> ResearchChat | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT chat_id, workspace_id, title, is_archived, created_at, updated_at
                   FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid""",
                chat_id, owner_id,
            )
        return ResearchChat.model_validate(dict(row)) if row else None

    async def rename_chat(self, owner_id: str, chat_id: UUID, title: str) -> ResearchChat | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE research_chats
                   SET title = $3, updated_at = NOW()
                   WHERE chat_id = $1 AND owner_id = $2::uuid
                   RETURNING chat_id, workspace_id, title, is_archived, created_at, updated_at""",
                chat_id, owner_id, title,
            )
        return ResearchChat.model_validate(dict(row)) if row else None

    async def archive_chat(
        self, owner_id: str, chat_id: UUID, is_archived: bool = True
    ) -> ResearchChat | None:
        async with self.pool.acquire() as conn:
            if is_archived:
                has_msgs = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM research_messages WHERE chat_id = $1)",
                    chat_id,
                )
                if not has_msgs:
                    await conn.execute(
                        "DELETE FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid",
                        chat_id, owner_id,
                    )
                    return None
            row = await conn.fetchrow(
                """UPDATE research_chats
                   SET is_archived = $3, updated_at = NOW()
                   WHERE chat_id = $1 AND owner_id = $2::uuid
                   RETURNING chat_id, workspace_id, title, is_archived, created_at, updated_at""",
                chat_id, owner_id, is_archived,
            )
        return ResearchChat.model_validate(dict(row)) if row else None

    # -- messages ------------------------------------------------------

    async def add_message(
        self,
        owner_id: str,
        chat_id: UUID,
        role: str,
        content: str,
        run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchMessage | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO research_messages (chat_id, run_id, role, content, metadata)
                   SELECT $1, $2, $3, $4, $5::jsonb
                   FROM research_chats c WHERE c.chat_id = $1 AND c.owner_id = $6::uuid
                   RETURNING message_id, chat_id, run_id, role, content, metadata, created_at""",
                chat_id, run_id, role, content, json.dumps(metadata or {}), owner_id,
            )
        return _row_model(ResearchMessage, row) if row else None

    async def list_messages(
        self, owner_id: str, chat_id: UUID, after_id: int = 0, limit: int = 50
    ) -> list[ResearchMessage]:
        limit = max(1, min(limit, 200))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT m.message_id, m.chat_id, m.run_id, m.role, m.content,
                          m.metadata, m.created_at
                   FROM research_messages m
                   JOIN research_chats c ON m.chat_id = c.chat_id
                   WHERE m.chat_id = $1 AND c.owner_id = $2::uuid AND m.message_id > $3
                   ORDER BY m.message_id ASC LIMIT $4""",
                chat_id, owner_id, after_id, limit,
            )
        return [_row_model(ResearchMessage, r) for r in rows]

    # -- runs ----------------------------------------------------------

    async def create_run(self, owner_id: str, chat_id: UUID, prompt: str) -> ResearchRun | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO research_runs (chat_id, status, prompt)
                   SELECT $1, 'queued', $2
                   FROM research_chats c WHERE c.chat_id = $1 AND c.owner_id = $3::uuid
                   RETURNING run_id, chat_id, status, prompt, error_code, error_message,
                             started_at, finished_at, created_at""",
                chat_id, prompt, owner_id,
            )
        return ResearchRun.model_validate(dict(row)) if row else None

    async def set_run_status(
        self,
        owner_id: str,
        run_id: UUID,
        status: RunStatus | str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ResearchRun | None:
        status_value = status.value if isinstance(status, RunStatus) else status
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE research_runs r SET status = $3::varchar, error_code = $4, error_message = $5,
                          started_at = CASE WHEN $3::varchar = 'running' THEN COALESCE(r.started_at, NOW()) ELSE r.started_at END,
                          finished_at = CASE WHEN $3::varchar IN ('completed','failed','cancelled') THEN NOW() ELSE r.finished_at END
                   FROM research_chats c
                   WHERE r.run_id = $1 AND r.chat_id = c.chat_id AND c.owner_id = $2::uuid
                   RETURNING r.run_id, r.chat_id, r.status, r.prompt, r.error_code,
                             r.error_message, r.started_at, r.finished_at, r.created_at""",
                run_id, owner_id, status_value, error_code, error_message,
            )
        return ResearchRun.model_validate(dict(row)) if row else None

    async def get_active_run(self, owner_id: str, chat_id: UUID) -> ResearchRun | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT r.run_id, r.chat_id, r.status, r.prompt, r.error_code,
                          r.error_message, r.started_at, r.finished_at, r.created_at
                   FROM research_runs r JOIN research_chats c ON r.chat_id = c.chat_id
                   WHERE r.chat_id = $1 AND c.owner_id = $2::uuid
                     AND r.status IN ('queued','running')
                   ORDER BY r.created_at DESC LIMIT 1""",
                chat_id, owner_id,
            )
        return ResearchRun.model_validate(dict(row)) if row else None

    # -- result sets ---------------------------------------------------

    async def save_result_set(
        self,
        owner_id: str,
        chat_id: UUID,
        kind: str,
        label: str,
        definition: dict[str, Any],
        members: Sequence[dict[str, Any]],
        run_id: UUID | None = None,
        summary: dict[str, Any] | None = None,
    ) -> ResultSetSummary | None:
        kind_value = kind.value if hasattr(kind, "value") else kind
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                owns = await conn.fetchval(
                    "SELECT 1 FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid",
                    chat_id, owner_id,
                )
                if not owns:
                    return None
                row = await conn.fetchrow(
                    """INSERT INTO research_result_sets
                           (chat_id, run_id, kind, label, definition, summary, row_count)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
                       RETURNING result_set_id, chat_id, run_id, kind, label, definition,
                                 summary, row_count, snapshot_at, created_at""",
                    chat_id, run_id, kind_value, label,
                    json.dumps(definition or {}), json.dumps(summary or {}), len(members),
                )
                if members:
                    await conn.executemany(
                        """INSERT INTO research_result_members
                               (result_set_id, ordinal, entity_type, entity_key, payload)
                           VALUES ($1, $2, $3, $4, $5::jsonb)""",
                        [
                            (
                                row["result_set_id"], ordinal,
                                m["entity_type"], m["entity_key"],
                                json.dumps(m.get("payload", {})),
                            )
                            for ordinal, m in enumerate(members)
                        ],
                    )
        return _row_model(ResultSetSummary, row)

    async def list_result_summaries(
        self, owner_id: str, chat_id: UUID, limit: int = 20
    ) -> list[ResultSetSummary]:
        limit = max(1, min(limit, 100))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.result_set_id, s.chat_id, s.run_id, s.kind, s.label,
                          s.definition, s.summary, s.row_count, s.snapshot_at, s.created_at
                   FROM research_result_sets s JOIN research_chats c ON s.chat_id = c.chat_id
                   WHERE s.chat_id = $1 AND c.owner_id = $2::uuid
                   ORDER BY s.created_at DESC LIMIT $3""",
                chat_id, owner_id, limit,
            )
        return [_row_model(ResultSetSummary, r) for r in rows]

    async def get_result_summary(
        self, owner_id: str, result_set_id: UUID
    ) -> ResultSetSummary | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT s.result_set_id, s.chat_id, s.run_id, s.kind, s.label,
                          s.definition, s.summary, s.row_count, s.snapshot_at, s.created_at
                   FROM research_result_sets s JOIN research_chats c ON s.chat_id = c.chat_id
                   WHERE s.result_set_id = $1 AND c.owner_id = $2::uuid""",
                result_set_id, owner_id,
            )
        return _row_model(ResultSetSummary, row) if row else None

    async def page_result_members(
        self, owner_id: str, result_set_id: UUID, offset: int = 0, limit: int = 100
    ) -> list[dict[str, Any]] | None:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        async with self.pool.acquire() as conn:
            owns = await conn.fetchrow(
                """SELECT s.result_set_id FROM research_result_sets s
                   JOIN research_chats c ON s.chat_id = c.chat_id
                   WHERE s.result_set_id = $1 AND c.owner_id = $2::uuid""",
                result_set_id, owner_id,
            )
            if not owns:
                return None
            rows = await conn.fetch(
                """SELECT ordinal, entity_type, entity_key, payload
                   FROM research_result_members
                   WHERE result_set_id = $1 ORDER BY ordinal ASC LIMIT $2 OFFSET $3""",
                result_set_id, limit, offset,
            )
        return [
            {
                "ordinal": r["ordinal"],
                "entity_type": r["entity_type"],
                "entity_key": r["entity_key"],
                "payload": _json(r["payload"]),
            }
            for r in rows
        ]

    # -- panels --------------------------------------------------------

    async def upsert_panel(
        self,
        owner_id: str,
        workspace_id: UUID,
        source_chat_id: UUID | None,
        panel_key: str,
        panel_type: str,
        title: str,
        result_set_id: UUID | None,
        layout: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ResearchPanel | None:
        # Accept the pre-workspace call shape while callers migrate: (owner, chat_id,
        # panel_key, panel_type, title, result_set_id, layout, config). The legacy
        # layout occupies the new result_set_id slot, so inspect that slot before
        # coercing any string: panel keys may themselves be UUID-shaped strings.
        legacy_call = isinstance(result_set_id, dict)
        if legacy_call:
            legacy_chat_id = workspace_id
            legacy_panel_key = source_chat_id
            legacy_panel_type = panel_key
            legacy_title = panel_type
            legacy_result_set_id = title
            legacy_layout = result_set_id
            legacy_config = layout
            workspace_id = legacy_chat_id
            source_chat_id = legacy_chat_id
            panel_key = legacy_panel_key
            panel_type = legacy_panel_type
            title = legacy_title
            result_set_id = legacy_result_set_id
            layout = legacy_layout or {}
            config = legacy_config
        panel_type_value = panel_type.value if hasattr(panel_type, "value") else panel_type
        if legacy_call:
            async with self.pool.acquire() as conn:
                workspace_id = await conn.fetchval(
                    "SELECT workspace_id FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid",
                    workspace_id, owner_id,
                )
            if workspace_id is None:
                return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO research_panels
                       (workspace_id, source_chat_id, result_set_id, panel_type, panel_key, title, layout, config)
                   SELECT $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb
                   FROM research_workspaces w
                   LEFT JOIN research_chats c ON c.chat_id = $2
                   LEFT JOIN research_result_sets rs ON rs.result_set_id = $3
                   LEFT JOIN research_chats rs_chat ON rs_chat.chat_id = rs.chat_id
                   WHERE w.workspace_id = $1 AND w.owner_id = $9::uuid
                     AND ($2 IS NULL OR (c.owner_id = $9::uuid AND c.workspace_id = $1))
                     AND ($3 IS NULL OR (
                         rs.result_set_id IS NOT NULL
                         AND rs_chat.chat_id = $2
                         AND rs_chat.owner_id = $9::uuid
                         AND rs_chat.workspace_id = $1
                     ))
                   ON CONFLICT (workspace_id, panel_key) DO UPDATE SET
                       source_chat_id = EXCLUDED.source_chat_id,
                       result_set_id = EXCLUDED.result_set_id,
                       panel_type = EXCLUDED.panel_type,
                       title = EXCLUDED.title,
                       config = EXCLUDED.config,
                       state = CASE WHEN research_panels.state = 'closed' THEN 'normal'
                                    ELSE research_panels.state END,
                       updated_at = NOW()
                   RETURNING panel_id, workspace_id, source_chat_id, result_set_id, panel_type, panel_key,
                             title, state, layout, config, created_at, updated_at""",
                workspace_id, source_chat_id, result_set_id, panel_type_value, panel_key, title,
                json.dumps(layout or {}), json.dumps(config or {}), owner_id,
            )
        if not row:
            return None
        panel = _row_model(ResearchPanel, row)
        # Normalise state to the PanelState enum for callers.
        object.__setattr__(panel, "state", PanelState(panel.state.value if hasattr(panel.state, "value") else str(panel.state)))
        return panel

    async def update_panel(
        self, owner_id: str, panel_id: UUID, mutation: PanelMutation
    ) -> ResearchPanel | None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                workspace_id = await conn.fetchval(
                    """SELECT w.workspace_id
                       FROM research_panels p
                       JOIN research_workspaces w ON w.workspace_id = p.workspace_id
                       WHERE p.panel_id = $1 AND w.owner_id = $2::uuid
                       FOR UPDATE OF w""", panel_id, owner_id,
                )
                if not workspace_id:
                    return None
                row = await conn.fetchrow(
                    "SELECT panel_id, state, layout FROM research_panels WHERE panel_id = $1 FOR UPDATE",
                    panel_id,
                )
                if not row:
                    return None
                current_layout = _json(row["layout"]) if not isinstance(row["layout"], dict) else dict(row["layout"])
                new_layout = dict(current_layout)
                if mutation.floating is not None:
                    new_layout["floating"] = mutation.floating.model_dump(mode="json")
                if mutation.bring_to_front:
                    max_rank = await conn.fetchval(
                        """SELECT COALESCE(MAX((layout->>'z_index')::int), 0)
                           FROM research_panels WHERE workspace_id = $1""", workspace_id,
                    )
                    max_rank = int(max_rank or 0)
                    if max_rank >= 1_000_000:
                        all_panels = await conn.fetch(
                            """SELECT panel_id, layout FROM research_panels
                               WHERE workspace_id = $1
                               ORDER BY COALESCE((layout->>'z_index')::int, 0) ASC, created_at ASC""",
                            workspace_id,
                        )
                        for rank, p in enumerate(all_panels, start=1):
                            p_layout = _json(p["layout"]) if not isinstance(p["layout"], dict) else dict(p["layout"])
                            p_layout["z_index"] = rank
                            await conn.execute(
                                "UPDATE research_panels SET layout = $2::jsonb WHERE panel_id = $1",
                                p["panel_id"], json.dumps(p_layout),
                            )
                        max_rank = len(all_panels)
                    new_layout["z_index"] = max_rank + 1
                new_state = (
                    mutation.state.value if hasattr(mutation.state, "value") else str(mutation.state)
                ) if mutation.state is not None else row["state"]
                updated_row = await conn.fetchrow(
                    """UPDATE research_panels SET state = $2, layout = $3::jsonb, updated_at = NOW()
                       WHERE panel_id = $1
                       RETURNING panel_id, workspace_id, source_chat_id, result_set_id, panel_type,
                                 panel_key, title, state, layout, config, created_at, updated_at""",
                    panel_id, new_state, json.dumps(new_layout),
                )
        if not updated_row:
            return None
        panel = _row_model(ResearchPanel, updated_row)
        object.__setattr__(panel, "state", PanelState(panel.state.value if hasattr(panel.state, "value") else str(panel.state)))
        return panel

    async def update_panel_state(
        self, owner_id: str, panel_id: UUID, state: PanelState | str
    ) -> ResearchPanel | None:
        state_enum = state if isinstance(state, PanelState) else PanelState(state)
        return await self.update_panel(owner_id, panel_id, PanelMutation(state=state_enum))

    async def list_workspace_panels(self, owner_id: str, workspace_id: UUID) -> list[ResearchPanel] | None:
        async with self.pool.acquire() as conn:
            owned = await conn.fetchval(
                "SELECT 1 FROM research_workspaces WHERE workspace_id = $1 AND owner_id = $2::uuid",
                workspace_id, owner_id,
            )
            if not owned:
                return None
            rows = await conn.fetch(
                """SELECT p.panel_id, p.workspace_id, p.source_chat_id, p.result_set_id,
                          p.panel_type, p.panel_key, p.title, p.state, p.layout, p.config,
                          p.created_at, p.updated_at
                   FROM research_panels p WHERE p.workspace_id = $1
                   ORDER BY p.created_at ASC""", workspace_id,
            )
        panels = [_row_model(ResearchPanel, r) for r in rows]
        for panel in panels:
            object.__setattr__(panel, "state", PanelState(panel.state.value if hasattr(panel.state, "value") else str(panel.state)))
        return panels

    async def list_panels(self, owner_id: str, chat_id: UUID) -> list[ResearchPanel]:
        async with self.pool.acquire() as conn:
            workspace_id = await conn.fetchval(
                "SELECT workspace_id FROM research_chats WHERE chat_id = $1 AND owner_id = $2::uuid",
                chat_id, owner_id,
            )
        if workspace_id is None:
            return []
        panels = await self.list_workspace_panels(owner_id, workspace_id)
        return panels or []
