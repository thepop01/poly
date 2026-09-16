"use client";

import { useState, useSyncExternalStore } from "react";
import CanvasTabs from "@/components/research/CanvasTabs";
import WorkspaceSelector from "@/components/research/WorkspaceSelector";
import type { WorkspaceTabType } from "@/types/research";
import ChatRail from "@/components/research/ChatRail";
import ChatTabs from "@/components/research/ChatTabs";
import PanelCanvas from "@/components/research/PanelCanvas";
import TradingPanel from "@/components/research/TradingPanel";
import PositionsBar from "@/components/research/PositionsBar";
import type { ResearchPosition } from "@/types/research";
import { useResearchHub } from "@/hooks/useResearchHub";

const RAIL_KEY = "pt-research-rail-width";
const RAIL_MIN = 280;
const RAIL_MAX = 560;
const DEFAULT_RAIL_WIDTH = 350;

function subscribeStorage(callback: () => void) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function getStoredRailWidth(): number {
  if (typeof window === "undefined") return DEFAULT_RAIL_WIDTH;
  try {
    const raw = Number(window.localStorage.getItem(RAIL_KEY));
    if (Number.isFinite(raw) && raw >= RAIL_MIN && raw <= RAIL_MAX) {
      return Math.max(raw, 340);
    }
  } catch {
    /* ignore */
  }
  return DEFAULT_RAIL_WIDTH;
}

export default function ResearchHub() {
  const hub = useResearchHub();
  const storedRailWidth = useSyncExternalStore(subscribeStorage, getStoredRailWidth, () => DEFAULT_RAIL_WIDTH);

  const [activeRailWidth, setActiveRailWidth] = useState<number | null>(null);
  const railWidth = activeRailWidth ?? storedRailWidth;

  const [isDraggingRail, setIsDraggingRail] = useState(false);
  const [isTerminalMaximized, setIsTerminalMaximized] = useState(false);
  const [mobileView, setMobileView] = useState<"chat" | "results">("chat");
  const [tradingPanelVisible, setTradingPanelVisible] = useState(true);
  const [tradingTerminalOpen, setTradingTerminalOpen] = useState(true);
  const [activeTabType, setActiveTabType] = useState<WorkspaceTabType>("wallet_groups");
  const [selectedPosition, setSelectedPosition] = useState<ResearchPosition | null>(null);
  const activeChat = hub.chats.find((c) => c.chat_id === hub.activeChatId) ?? null;
  const activeId = activeChat?.chat_id ?? null;

  const [prevChatId, setPrevChatId] = useState<string | null>(activeId);
  if (prevChatId !== activeId) {
    setPrevChatId(activeId);
    setSelectedPosition(null);
  }

  const clampRail = (width: number) => {
    const clamped = Math.min(RAIL_MAX, Math.max(RAIL_MIN, Math.round(width)));
    try {
      window.localStorage.setItem(RAIL_KEY, String(clamped));
    } catch {
      /* ignore */
    }
    setActiveRailWidth(clamped);
    return clamped;
  };

  const handleStartDragRail = (e: React.PointerEvent) => {
    e.preventDefault();
    setIsDraggingRail(true);
    const startX = e.clientX;
    const startWidth = railWidth;

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const deltaX = moveEvent.clientX - startX;
      clampRail(startWidth - deltaX);
    };

    const handlePointerUp = () => {
      setIsDraggingRail(false);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  };

  const activeWorkspaceId = hub.activeWorkspaceId;
  const allPanels = activeWorkspaceId ? hub.panelsByWorkspace[activeWorkspaceId] ?? [] : [];
  const positions = activeId ? hub.positionsForChat(activeId) : [];

  const handleToggleTradingTerminal = () => {
    setTradingTerminalOpen((prev) => {
      const next = !prev;
      if (next && typeof document !== "undefined") {
        setTimeout(() => {
          document.querySelector(".trading-terminal")?.scrollIntoView({ behavior: "smooth" });
        }, 50);
      }
      return next;
    });
  };

  return (
    <div className="research-workspace" data-testid="research-workspace">
      {/* ── Top: Chat tab bar ── */}
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

      <div className="research-canvas-controls">
        <WorkspaceSelector
          workspaces={hub.workspaces}
          activeWorkspaceId={hub.activeWorkspaceId}
          onSelect={hub.selectWorkspace}
          onCreate={() => hub.createWorkspace()}
          onRename={hub.renameWorkspace}
          onDelete={hub.deleteWorkspace}
        />
        {hub.workspaceError && <p role="alert" className="research-workspace-error">{hub.workspaceError}</p>}
        <CanvasTabs
          tabs={activeWorkspaceId ? hub.tabsByWorkspace[activeWorkspaceId] : undefined}
          activeTabType={activeTabType}
          onSelect={setActiveTabType}
        />
      </div>

      {/* ── Mobile view switcher (hidden on md+) ── */}
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

      {/* ── Upper Section: Canvas (Left) | Chat Terminal (Right) ── */}
      <div className={`research-upper-workspace ${isTerminalMaximized ? "research-upper-collapsed" : ""}`}>
        {/* Left: Canvas area (directly beside app sidebar) */}
        <section
          aria-label="Results"
          className={`research-canvas ${mobileView === "results" ? "flex" : "hidden"} md:flex`}
        >
          <div
              id="research-canvas"
              role="tabpanel"
              aria-label={activeChat ? `Results for ${activeChat.title}` : "Workspace canvas"}
              className="research-canvas-scroll"
            >
              <PanelCanvas
                workspaceId={activeWorkspaceId}
                panels={allPanels}
                onPanelState={(panelId, state) => { if (activeWorkspaceId) void hub.setPanelState(activeWorkspaceId, panelId, state); }}
                onSaveMutation={async (panelId, mutation) => {
                  return activeWorkspaceId ? await hub.mutatePanel(activeWorkspaceId, panelId, mutation) : null;
                }}
              />
            </div>
        </section>

        {/* Drag splitter between Canvas and Chat Terminal */}
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
              clampRail(railWidth + (e.key === "ArrowLeft" ? 16 : -16));
            }
          }}
          onPointerDown={handleStartDragRail}
          className={`research-splitter hidden md:flex ${isDraggingRail ? "research-splitter-active" : ""}`}
        >
          <div className="research-splitter-grip" />
        </div>

        {/* Right: Chat rail / terminal */}
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
            onSend={async (prompt) => {
              let targetId = activeId;
              if (!targetId) {
                const newChat = await hub.createChat();
                targetId = newChat.chat_id;
              }
              await hub.sendPrompt(targetId, prompt);
            }}
            onStop={() => activeId && hub.stopRun(activeId)}
            onConsumeRestore={() => activeId && hub.consumeRestorePrompt(activeId)}
          />
        </section>
      </div>

      {/* ── Lower Section: Trading Terminal (Positions Bar + Buy/Sell Ticket) ── */}
      <section
        aria-label="Trading terminal"
        className={`trading-terminal ${tradingTerminalOpen ? "trading-terminal-open" : "trading-terminal-closed"} ${isTerminalMaximized ? "trading-terminal-maximized" : ""}`}
      >
        {/* Left: Positions dock */}
        <div className="trading-terminal-positions">
          <PositionsBar
            rows={positions}
            chatTitle={activeChat?.title}
            selectedPosition={selectedPosition}
            onSelectPosition={(pos) => setSelectedPosition(pos)}
            isOpen={tradingTerminalOpen}
            onToggleOpen={handleToggleTradingTerminal}
            isMaximized={isTerminalMaximized}
            onToggleMaximized={() => setIsTerminalMaximized((m) => !m)}
          />
        </div>

        {/* Right: Buy/Sell Trading Panel */}
        <div className="trading-terminal-ticket">
          <TradingPanel
            selectedPosition={selectedPosition ?? undefined}
            visible={tradingPanelVisible}
            onToggle={() => setTradingPanelVisible((v) => !v)}
          />
        </div>
      </section>
    </div>
  );
}
