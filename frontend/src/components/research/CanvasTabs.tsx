"use client";

import type { ResearchWorkspaceTab, WorkspaceTabType } from "@/types/research";

export interface CanvasTabsProps {
  tabs: ResearchWorkspaceTab[] | undefined;
  activeTabType: WorkspaceTabType;
  onSelect: (tabType: WorkspaceTabType) => void;
}

const CANVAS_TABS: readonly { type: WorkspaceTabType; label: string }[] = [
  { type: "wallet_groups", label: "Wallet Groups" },
  { type: "market_groups", label: "Market Groups" },
  { type: "agents", label: "Agents" },
];

export default function CanvasTabs({ tabs, activeTabType, onSelect }: CanvasTabsProps) {
  const loading = tabs === undefined;
  return (
    <div className="research-canvas-tabs" role="tablist" aria-label="Research canvas tabs" aria-busy={loading}>
      {CANVAS_TABS.map(({ type, label }) => {
        const selected = activeTabType === type;
        return (
          <button
            key={type}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls="research-canvas"
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(type)}
            onKeyDown={(event) => {
              if ((event.key === "Enter" || event.key === " ") && !event.defaultPrevented) {
                event.preventDefault();
                onSelect(type);
              }
            }}
            className={`research-canvas-tab${selected ? " research-canvas-tab-active" : ""}`}
          >
            {label}
          </button>
        );
      })}
      {loading && <span className="research-canvas-tabs-loading">Loading canvas tabs…</span>}
    </div>
  );
}
