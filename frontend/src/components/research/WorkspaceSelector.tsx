"use client";

import { useState } from "react";
import type { ResearchWorkspace } from "@/types/research";

export interface WorkspaceSelectorProps {
  workspaces: ResearchWorkspace[];
  activeWorkspaceId: string | null;
  onSelect: (workspaceId: string) => void;
  onCreate: () => void;
  onRename: (workspaceId: string, name: string) => void;
  onDelete: (workspaceId: string) => void;
}

export default function WorkspaceSelector({
  workspaces,
  activeWorkspaceId,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: WorkspaceSelectorProps) {
  const active = workspaces.find((workspace) => workspace.workspace_id === activeWorkspaceId) ?? null;
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const beginRename = () => {
    if (!active) return;
    setEditingId(active.workspace_id);
    setDraft(active.name);
  };

  const commitRename = () => {
    if (editingId && draft.trim()) onRename(editingId, draft.trim());
    setEditingId(null);
  };

  return (
    <section className="research-workspace-selector" aria-label="Research workspace">
      <label htmlFor="research-workspace-select" className="research-control-label">
        Workspace
      </label>
      <select
        id="research-workspace-select"
        aria-label="Research workspace"
        value={activeWorkspaceId ?? ""}
        onChange={(event) => onSelect(event.target.value)}
        disabled={workspaces.length === 0}
        className="research-workspace-select"
      >
        {workspaces.length === 0 ? (
          <option value="">No workspaces</option>
        ) : (
          workspaces.map((workspace) => (
            <option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.name}
            </option>
          ))
        )}
      </select>
      <button type="button" onClick={onCreate} className="research-workspace-action" aria-label="Create workspace">
        +
      </button>
      <button
        type="button"
        onClick={beginRename}
        disabled={!active}
        className="research-workspace-action"
        aria-label={active ? `Rename ${active.name}` : "Rename workspace"}
      >
        Rename
      </button>
      <button
        type="button"
        onClick={() => active && onDelete(active.workspace_id)}
        disabled={!active}
        className="research-workspace-action research-workspace-delete"
        aria-label={active ? `Delete ${active.name}` : "Delete workspace"}
      >
        Delete
      </button>
      {editingId && (
        <div className="research-workspace-rename" role="group" aria-label="Rename workspace">
          <input
            autoFocus
            aria-label="Workspace name"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitRename();
              if (event.key === "Escape") setEditingId(null);
            }}
          />
          <button type="button" onClick={commitRename} aria-label="Save workspace name">
            Save
          </button>
        </div>
      )}
    </section>
  );
}
