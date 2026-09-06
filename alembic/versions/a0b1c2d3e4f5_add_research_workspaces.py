"""Add permanent research workspaces and migrate chat panels.

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "z9a0b1c2d3e4"
branch_labels = None
depends_on = None


def _add_constraint_if_missing(table: str, constraint: str, definition: str) -> None:
    """Add a named constraint, rejecting same-name definition drift."""
    normalized_definition = " ".join(definition.lower().split())
    op.execute(
        f"""
DO $$
DECLARE
    actual_definition text;
BEGIN
    SELECT regexp_replace(lower(pg_get_constraintdef(c.oid)), '[[:space:]]+', ' ', 'g')
      INTO actual_definition
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname = '{table}'
      AND c.conname = '{constraint}';

    IF actual_definition IS NULL THEN
        ALTER TABLE {table} ADD CONSTRAINT {constraint} {definition};
    ELSIF actual_definition <> '{normalized_definition}' THEN
        RAISE EXCEPTION 'Constraint {constraint} on {table} has unexpected definition: %',
            actual_definition;
    END IF;
END $$;
"""
    )


def _drop_constraints_referencing(table: str, referenced_table: str) -> None:
    """Drop foreign keys from table to referenced_table, including old names."""
    op.execute(
        f"""
DO $$
DECLARE
    constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_class rt ON rt.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_namespace rn ON rn.oid = rt.relnamespace
        WHERE n.nspname = 'public'
          AND rn.nspname = 'public'
          AND t.relname = '{table}'
          AND rt.relname = '{referenced_table}'
          AND c.contype = 'f'
    LOOP
        EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END $$;
"""
    )


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS research_workspaces (
    workspace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_research_workspaces_owner_updated
    ON research_workspaces(owner_id, updated_at DESC)
"""
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS research_workspace_tabs (
    workspace_tab_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES research_workspaces(workspace_id) ON DELETE CASCADE,
    tab_type VARCHAR(32) NOT NULL CHECK (
        tab_type IN ('wallet_groups', 'market_groups', 'agents')
    ),
    label VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, tab_type)
)
"""
    )

    # Add the nullable column first so this remains safe if an earlier attempt
    # stopped after creating the workspace tables.
    op.execute("ALTER TABLE research_chats ADD COLUMN IF NOT EXISTS workspace_id UUID")

    # Every legacy chat with no workspace gets a stable, chat-derived
    # workspace. Existing assignments are never rewritten: a retry may see a
    # workspace selected by a later application migration, and moving that chat
    # back to its deterministic workspace would split its canvas.
    op.execute(
        """
INSERT INTO research_workspaces (workspace_id, owner_id, name, created_at, updated_at)
SELECT md5('research-workspace:' || c.chat_id::text)::uuid,
       c.owner_id,
       LEFT(c.title, 110) || ' workspace',
       c.created_at,
       c.updated_at
FROM research_chats c
WHERE c.workspace_id IS NULL
ON CONFLICT (workspace_id) DO NOTHING
"""
    )
    # Seed every workspace, not only deterministic legacy-chat workspaces.
    # This also repairs a partial run and covers workspaces created by later
    # application code before a retry reaches this migration.
    op.execute(
        """
INSERT INTO research_workspace_tabs (workspace_id, tab_type, label)
SELECT w.workspace_id, tabs.tab_type, tabs.label
FROM research_workspaces w
CROSS JOIN (
    VALUES
        ('wallet_groups'::varchar(32), 'Wallet Groups'::varchar(80)),
        ('market_groups'::varchar(32), 'Market Groups'::varchar(80)),
        ('agents'::varchar(32), 'Agents'::varchar(80))
) AS tabs(tab_type, label)
ON CONFLICT (workspace_id, tab_type) DO NOTHING
"""
    )
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM research_workspaces w
        WHERE NOT EXISTS (
            SELECT 1 FROM research_workspace_tabs t
            WHERE t.workspace_id = w.workspace_id AND t.tab_type = 'wallet_groups'
        )
        OR NOT EXISTS (
            SELECT 1 FROM research_workspace_tabs t
            WHERE t.workspace_id = w.workspace_id AND t.tab_type = 'market_groups'
        )
        OR NOT EXISTS (
            SELECT 1 FROM research_workspace_tabs t
            WHERE t.workspace_id = w.workspace_id AND t.tab_type = 'agents'
        )
    ) THEN
        RAISE EXCEPTION 'Cannot backfill workspace tabs: every workspace must have all three fixed tabs';
    END IF;
END $$;
"""
    )
    op.execute(
        """
UPDATE research_chats
SET workspace_id = md5('research-workspace:' || chat_id::text)::uuid
WHERE workspace_id IS NULL
"""
    )
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM research_chats c
        LEFT JOIN research_workspaces w ON w.workspace_id = c.workspace_id
        WHERE c.workspace_id IS NOT NULL AND w.workspace_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot backfill research_chats.workspace_id: existing assignment has no workspace';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM research_chats c
        JOIN research_workspaces w ON w.workspace_id = c.workspace_id
        WHERE c.owner_id <> w.owner_id
    ) THEN
        RAISE EXCEPTION 'Cannot backfill research_chats.workspace_id: chat and workspace owners differ';
    END IF;
END $$;
"""
    )
    _add_constraint_if_missing(
        "research_chats",
        "research_chats_workspace_id_fkey",
        "FOREIGN KEY (workspace_id) REFERENCES research_workspaces(workspace_id) ON DELETE CASCADE",
    )
    op.execute("ALTER TABLE research_chats ALTER COLUMN workspace_id SET NOT NULL")

    # Preserve the source chat as nullable provenance while moving ownership to
    # the workspace.  Column/constraint checks make a retried upgrade harmless.
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'research_panels'
          AND column_name = 'chat_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'research_panels'
          AND column_name = 'source_chat_id'
    ) THEN
        ALTER TABLE research_panels RENAME COLUMN chat_id TO source_chat_id;
    END IF;
END $$;
"""
    )
    op.execute("ALTER TABLE research_panels ADD COLUMN IF NOT EXISTS workspace_id UUID")
    op.execute("ALTER TABLE research_panels ALTER COLUMN source_chat_id DROP NOT NULL")
    _drop_constraints_referencing("research_panels", "research_chats")
    op.execute(
        """
UPDATE research_panels p
SET workspace_id = c.workspace_id
FROM research_chats c
WHERE p.source_chat_id = c.chat_id
  AND p.workspace_id IS NULL
"""
    )
    # A legacy panel always has a source chat. Fail loudly rather than assign
    # it to an arbitrary workspace if the source data is inconsistent, and do
    # not rewrite an ownership assignment made by a partial/later upgrade.
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM research_panels p
        JOIN research_chats c ON c.chat_id = p.source_chat_id
        WHERE p.workspace_id <> c.workspace_id
    ) THEN
        RAISE EXCEPTION 'Cannot backfill research_panels.workspace_id: existing assignment conflicts with source chat workspace';
    END IF;
    IF EXISTS (SELECT 1 FROM research_panels WHERE workspace_id IS NULL) THEN
        RAISE EXCEPTION 'Cannot backfill research_panels.workspace_id: panel has no source chat workspace';
    END IF;
END $$;
"""
    )
    _add_constraint_if_missing(
        "research_panels",
        "research_panels_source_chat_id_fkey",
        "FOREIGN KEY (source_chat_id) REFERENCES research_chats(chat_id) ON DELETE SET NULL",
    )
    _add_constraint_if_missing(
        "research_panels",
        "research_panels_workspace_id_fkey",
        "FOREIGN KEY (workspace_id) REFERENCES research_workspaces(workspace_id) ON DELETE CASCADE",
    )
    op.execute("ALTER TABLE research_panels ALTER COLUMN workspace_id SET NOT NULL")

    # The old generated unique constraint is no longer valid after ownership
    # moves to workspaces.  Drop it by its legacy name and guard the new one.
    op.execute(
        "ALTER TABLE research_panels DROP CONSTRAINT IF EXISTS research_panels_chat_id_panel_key_key"
    )
    _add_constraint_if_missing(
        "research_panels",
        "research_panels_workspace_panel_key_key",
        "UNIQUE (workspace_id, panel_key)",
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_research_panels_workspace
    ON research_panels(workspace_id, created_at ASC)
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_research_panels_source_chat
    ON research_panels(source_chat_id)
    WHERE source_chat_id IS NOT NULL
"""
    )


def downgrade() -> None:
    # A workspace can contain multiple chats.  Reverting ownership would then
    # silently merge independent canvases, so refuse that downgrade explicitly.
    conn = op.get_bind()
    if conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM research_panels p
                JOIN (
                    SELECT workspace_id
                    FROM research_chats
                    GROUP BY workspace_id
                    HAVING COUNT(*) > 1
                ) multi ON multi.workspace_id = p.workspace_id
            )
            """
        )
    ).scalar():
        raise NotImplementedError(
            "Cannot downgrade research workspaces: a workspace owns multiple chats"
        )
    if conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM research_panels WHERE source_chat_id IS NULL)")
    ).scalar():
        raise NotImplementedError(
            "Cannot downgrade research workspaces: a panel has no source chat"
        )
    op.execute("DROP INDEX IF EXISTS idx_research_panels_source_chat")
    op.execute("DROP INDEX IF EXISTS idx_research_panels_workspace")
    op.execute(
        "ALTER TABLE research_panels DROP CONSTRAINT IF EXISTS research_panels_workspace_panel_key_key"
    )
    op.execute(
        "ALTER TABLE research_panels DROP CONSTRAINT IF EXISTS research_panels_workspace_id_fkey"
    )
    op.execute(
        "ALTER TABLE research_panels DROP CONSTRAINT IF EXISTS research_panels_source_chat_id_fkey"
    )
    op.execute(
        "ALTER TABLE research_panels DROP CONSTRAINT IF EXISTS research_panels_chat_id_fkey"
    )
    op.execute("ALTER TABLE research_panels DROP COLUMN IF EXISTS workspace_id")
    # Copy provenance into a new legacy ownership column before removing the
    # workspace-era source column; this keeps the downgrade data-preserving.
    op.execute("ALTER TABLE research_panels ADD COLUMN IF NOT EXISTS chat_id UUID")
    op.execute(
        """
UPDATE research_panels
SET chat_id = source_chat_id
WHERE chat_id IS NULL
  AND source_chat_id IS NOT NULL
"""
    )
    op.execute("ALTER TABLE research_panels ALTER COLUMN chat_id SET NOT NULL")
    op.execute("ALTER TABLE research_panels DROP COLUMN IF EXISTS source_chat_id")
    _add_constraint_if_missing(
        "research_panels",
        "research_panels_chat_id_fkey",
        "FOREIGN KEY (chat_id) REFERENCES research_chats(chat_id) ON DELETE CASCADE",
    )
    _add_constraint_if_missing(
        "research_panels",
        "research_panels_chat_id_panel_key_key",
        "UNIQUE (chat_id, panel_key)",
    )
    op.execute("ALTER TABLE research_chats DROP CONSTRAINT IF EXISTS research_chats_workspace_id_fkey")
    op.execute("ALTER TABLE research_chats DROP COLUMN IF EXISTS workspace_id")
    op.execute("DROP TABLE IF EXISTS research_workspace_tabs")
    op.execute("DROP TABLE IF EXISTS research_workspaces")
