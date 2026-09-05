"use client";

import { useRef, useState } from "react";
import ChatRail from "@/components/research/ChatRail";
import ChatTabs from "@/components/research/ChatTabs";
import EmptyResearchState from "@/components/research/EmptyResearchState";
import PanelCanvas from "@/components/research/PanelCanvas";
import { useResearchHub } from "@/hooks/useResearchHub";

const RAIL_KEY = "pt-research-rail-width";
const RAIL_MIN = 300;
const RAIL_MAX = 560;

function initialRailWidth(): number {
  if (typeof window === "undefined") return 360;
  const raw = Number(window.localStorage.getItem(RAIL_KEY));
  if (Number.isFinite(raw) && raw >= RAIL_MIN && raw <= RAIL_MAX) return raw;
  return 360;
}

export default function ResearchHub() {
  const hub = useResearchHub();
  const [railWidth, setRailWidth] = useState(initialRailWidth);
  const [mobileView, setMobileView] = useState<"chat" | "results">("chat");
  const dragState = useRef<{ startX: number; startWidth: number } | null>(null);
  const activeChat = hub.chats.find((c) => c.chat_id === hub.activeChatId) ?? null;
  const activeId = activeChat?.chat_id ?? null;

  const clampRail = (width: number) => {
    const clamped = Math.min(RAIL_MAX, Math.max(RAIL_MIN, Math.round(width)));
    window.localStorage.setItem(RAIL_KEY, String(clamped));
    return clamped;
  };

  return (
    <div className="research-workspace" data-testid="research-workspace">
      <ChatTabs
        chats={hub.chats}
        archivedChats={hub.archivedChats}
        activeChatId={hub.activeChatId}
        loading={hub.loading}
        onSelect={hub.selectChat}
        onCreate={() => hub.createChat()}
        onRename={(id, title) => hub.renameChat(id, title)}
        onClose={(id) => hub.closeChat(id)}
        onReopen={(id) => hub.reopenChat(id)}
      />
      <div className="research-view-switch" role="group" aria-label="Workspace view">
        {(["chat", "results"] as const).map((view) => (
          <button
            key={view}
            type="button"
            aria-pressed={mobileView === view}
            onClick={() => setMobileView(view)}
            className={`rounded-md px-3 py-1 text-sm font-medium ${
              mobileView === view
                ? "bg-primary/10 text-primary"
                : "text-subtle hover:text-foreground"
            }`}
          >
            {view === "chat" ? "Chat" : "Results"}
          </button>
        ))}
      </div>
      <div className="research-split">
        <section
          aria-label="Conversation"
          className={`research-rail ${mobileView === "chat" ? "flex flex-col" : "hidden"} md:flex md:flex-col`}
          style={{ width: railWidth }}
          data-rail-width={railWidth}
        >
          <ChatRail
            chatId={activeId}
            messages={activeId ? hub.messagesByChat[activeId] ?? [] : []}
            results={activeId ? hub.resultsForChat(activeId) : []}
            busy={activeId ? hub.busyByChat[activeId] ?? false : false}
            status={activeId ? hub.statusByChat[activeId] ?? null : null}
            error={activeId ? hub.errorByChat[activeId] ?? null : null}
            streamingText={activeId ? hub.streamingTextByChat[activeId] ?? "" : ""}
            restorePrompt={activeId ? hub.restorePromptByChat[activeId] ?? null : null}
            onSend={(prompt) => activeId && hub.sendPrompt(activeId, prompt)}
            onStop={() => activeId && hub.stopRun(activeId)}
            onConsumeRestore={() => activeId && hub.consumeRestorePrompt(activeId)}
          />
        </section>
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize conversation panel"
          aria-valuenow={railWidth}
          aria-valuemin={RAIL_MIN}
          aria-valuemax={RAIL_MAX}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
              e.preventDefault();
              setRailWidth((w) => clampRail(w + (e.key === "ArrowRight" ? 16 : -16)));
            }
          }}
          onPointerDown={(e) => {
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            dragState.current = { startX: e.clientX, startWidth: railWidth };
          }}
          onPointerMove={(e) => {
            const drag = dragState.current;
            if (!drag || e.buttons === 0) return;
            setRailWidth(clampRail(drag.startWidth + e.clientX - drag.startX));
          }}
          onPointerUp={() => {
            dragState.current = null;
          }}
          className="research-splitter"
        />
        <section
          aria-label="Results"
          className={`research-canvas ${mobileView === "results" ? "flex" : "hidden"} md:flex`}
        >
          {!activeChat || !activeId ? (
            <EmptyResearchState
              onPick={async (prompt) => {
                const chat = await hub.createChat();
                await hub.sendPrompt(chat.chat_id, prompt);
              }}
            />
          ) : (
            <div
              id={`research-panel-${activeChat.chat_id}`}
              role="tabpanel"
              aria-label={`Results for ${activeChat.title}`}
              className="research-canvas-scroll"
            >
              <PanelCanvas
                panels={hub.panelsByChat[activeId] ?? []}
                onPanelState={(panelId, state) => hub.setPanelState(activeId, panelId, state)}
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
