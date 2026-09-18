"use client";

import { useEffect, useRef, useState } from "react";
import type { ResearchWorkspace } from "@/types/research";
import { Plus, Edit2, X, FolderKanban } from "lucide-react";

export interface WorkspaceTabsProps {
  workspaces: ResearchWorkspace[];
  activeWorkspaceId: string | null;
  loading?: boolean;
  onSelect: (workspaceId: string) => void;
  onCreate: () => void;
  onRename: (workspaceId: string, name: string) => void;
  onDelete: (workspaceId: string) => void;
}

export default function WorkspaceTabs({
  workspaces,
  activeWorkspaceId,
  loading = false,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: WorkspaceTabsProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const editRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId) {
      editRef.current?.focus();
      editRef.current?.select();
    }
  }, [editingId]);

  const commitRename = (workspaceId: string) => {
    const trimmed = draft.trim();
    if (trimmed) {
      onRename(workspaceId, trimmed);
    }
    setEditingId(null);
  };

  return (
    <div className="research-tabs border-b border-border bg-surface px-3 py-1.5 flex items-center gap-1.5 min-h-[44px]" role="tablist" aria-label="Research Workspaces">
      <div className="flex items-center gap-1.5 mr-2 text-subtle font-bold text-xs uppercase tracking-wider select-none flex-shrink-0">
        <FolderKanban size={14} className="text-primary" />
        <span>Canvas</span>
      </div>

      {loading && workspaces.length === 0 ? (
        <span className="text-xs font-semibold text-subtle px-2">Loading workspaces…</span>
      ) : (
        <div className="flex items-center gap-1 overflow-x-auto flex-1 min-w-0">
          {workspaces.map((workspace) => {
            const active = workspace.workspace_id === activeWorkspaceId;
            return (
              <div
                key={workspace.workspace_id}
                role="tab"
                aria-selected={active}
                tabIndex={0}
                onClick={() => onSelect(workspace.workspace_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(workspace.workspace_id);
                  }
                }}
                className={`research-tab group flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-all cursor-pointer select-none max-w-[220px] ${
                  active
                    ? "bg-surface-2 border-primary/40 text-foreground font-bold shadow-xs"
                    : "border-transparent text-muted-fg font-semibold hover:bg-surface-2 hover:text-foreground"
                }`}
              >
                {editingId === workspace.workspace_id ? (
                  <input
                    ref={editRef}
                    value={draft}
                    aria-label="Workspace name"
                    onChange={(e) => setDraft(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={() => commitRename(workspace.workspace_id)}
                    onKeyDown={(e) => {
                      e.stopPropagation();
                      if (e.key === "Enter") commitRename(workspace.workspace_id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="w-28 rounded border border-border bg-surface px-1.5 py-0.5 text-xs font-bold text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
                  />
                ) : (
                  <span
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditingId(workspace.workspace_id);
                      setDraft(workspace.name);
                    }}
                    title="Double-click to rename workspace"
                    className="truncate max-w-36 text-left font-bold"
                  >
                    {workspace.name}
                  </span>
                )}

                <span className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity ml-1">
                  <button
                    type="button"
                    aria-label={`Rename ${workspace.name}`}
                    title="Rename workspace"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingId(workspace.workspace_id);
                      setDraft(workspace.name);
                    }}
                    className="p-0.5 rounded text-subtle hover:text-foreground hover:bg-surface-3 transition-colors"
                  >
                    <Edit2 size={11} />
                  </button>
                  {workspaces.length > 1 && (
                    <button
                      type="button"
                      aria-label={`Delete ${workspace.name}`}
                      title="Delete workspace"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete workspace "${workspace.name}"?`)) {
                          onDelete(workspace.workspace_id);
                        }
                      }}
                      className="p-0.5 rounded text-subtle hover:text-danger hover:bg-surface-3 transition-colors"
                    >
                      <X size={12} />
                    </button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <button
        type="button"
        aria-label="New research workspace"
        title="Create new research workspace"
        onClick={onCreate}
        className="flex items-center gap-1 rounded-md bg-primary/10 hover:bg-primary/20 text-primary border border-primary/25 px-2.5 py-1 text-xs font-bold transition-all flex-shrink-0 cursor-pointer"
      >
        <Plus size={13} className="stroke-[2.5]" />
        <span>New Canvas</span>
      </button>
    </div>
  );
}
