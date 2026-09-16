"use client";

import { useEffect, useRef, useState } from "react";
import type { ResearchChat } from "@/types/research";

interface ChatTabsProps {
  chats: ResearchChat[];
  archivedChats: ResearchChat[];
  activeChatId: string | null;
  loading: boolean;
  onSelect: (chatId: string) => void;
  onCreate: () => void;
  onRename: (chatId: string, title: string) => void;
  onClose: (chatId: string) => void;
  onReopen: (chatId: string) => void;
}

export default function ChatTabs({
  chats,
  archivedChats,
  activeChatId,
  loading,
  onSelect,
  onCreate,
  onRename,
  onClose,
  onReopen,
}: ChatTabsProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const editRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId) editRef.current?.focus();
  }, [editingId]);

  const commitRename = (chatId: string) => {
    const title = draft.trim();
    if (title) onRename(chatId, title);
    setEditingId(null);
  };

  return (
    <div className="research-tabs" role="tablist" aria-label="Research chats">
      {loading ? (
        <span className="text-sm text-subtle px-2">Loading chats…</span>
      ) : (
        <div className="flex items-center gap-1 overflow-x-auto flex-1 min-w-0">
          {chats.map((chat) => {
            const active = chat.chat_id === activeChatId;
            return (
              <div
                key={chat.chat_id}
                role="tab"
                aria-selected={active}
                aria-controls={`research-panel-${chat.chat_id}`}
                tabIndex={0}
                onClick={() => onSelect(chat.chat_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") onSelect(chat.chat_id);
                }}
                className={`research-tab${active ? " research-tab-active" : ""}`}
              >
                {editingId === chat.chat_id ? (
                  <input
                    ref={editRef}
                    value={draft}
                    aria-label="Chat title"
                    onChange={(e) => setDraft(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={() => commitRename(chat.chat_id)}
                    onKeyDown={(e) => {
                      e.stopPropagation();
                      if (e.key === "Enter") commitRename(chat.chat_id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="w-32 rounded border border-border bg-surface px-1 text-sm"
                  />
                ) : (
                  <button
                    type="button"
                    onDoubleClick={() => {
                      setEditingId(chat.chat_id);
                      setDraft(chat.title);
                    }}
                    title="Double-click to rename"
                    className="truncate max-w-40 text-left"
                  >
                    {chat.title}
                  </button>
                )}
                <span className="research-tab-actions">
                  <button
                    type="button"
                    aria-label={`Rename ${chat.title}`}
                    title="Rename"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingId(chat.chat_id);
                      setDraft(chat.title);
                    }}
                    className="research-tab-icon-btn"
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    aria-label={`Close ${chat.title}`}
                    title="Close (keeps history)"
                    onClick={(e) => {
                      e.stopPropagation();
                      onClose(chat.chat_id);
                    }}
                    className="research-tab-icon-btn"
                  >
                    ×
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div className="flex items-center gap-1 flex-shrink-0">
        {archivedChats.length > 0 && (
          <div className="relative">
            <button
              type="button"
              aria-label="Reopen closed chats"
              aria-expanded={archiveOpen}
              onClick={() => setArchiveOpen((v) => !v)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-muted-fg hover:bg-surface-2"
            >
              Closed ({archivedChats.length})
            </button>
            {archiveOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 w-56 rounded-lg border border-border bg-surface p-1 shadow-lg">
                {archivedChats.map((chat) => (
                  <button
                    key={chat.chat_id}
                    type="button"
                    onClick={() => {
                      onReopen(chat.chat_id);
                      setArchiveOpen(false);
                    }}
                    className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                  >
                    {chat.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          aria-label="New research chat"
          title="New research chat"
          onClick={onCreate}
          className="rounded-md bg-primary px-2.5 py-1 text-sm font-semibold text-white hover:bg-primary/90"
        >
          +
        </button>
      </div>
    </div>
  );
}
