"use client";

import type { ResearchPanel } from "@/types/research";

interface PanelFrameProps {
  panel: ResearchPanel;
  hidden?: boolean;
  onState: (panelId: string, state: ResearchPanel["state"]) => void;
  children: React.ReactNode;
}

function metaLine(panel: ResearchPanel): string {
  const config = panel.config as {
    snapshot_at?: string;
    row_count?: number;
    summary?: { evidence_floor?: number; scope?: Record<string, unknown> };
  };
  const parts: string[] = [];
  if (config.snapshot_at) {
    parts.push(`Snapshot ${new Date(config.snapshot_at).toLocaleString()}`);
  }
  if (typeof config.row_count === "number") parts.push(`${config.row_count} rows`);
  const scope = config.summary?.scope as Record<string, unknown> | undefined;
  if (scope) {
    const path = [scope.category, scope.subcategory, scope.league].filter(Boolean).join(" → ");
    if (path) parts.push(path);
  }
  if (typeof config.summary?.evidence_floor === "number") {
    parts.push(`floor n≥${config.summary.evidence_floor}`);
  }
  return parts.join(" · ");
}

export default function PanelFrame({ panel, hidden, onState, children }: PanelFrameProps) {
  const meta = metaLine(panel);
  return (
    <article
      aria-label={panel.title}
      data-testid={`panel-${panel.panel_id}`}
      className={`research-panel${panel.state === "minimized" ? " research-panel-minimized" : ""}`}
      hidden={hidden}
    >
      <header className="research-panel-header">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-foreground">{panel.title}</h3>
          {meta && <p className="truncate text-xs text-subtle">{meta}</p>}
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          {panel.state === "minimized" ? (
            <button
              type="button"
              aria-label={`Restore ${panel.title}`}
              title="Restore"
              onClick={() => onState(panel.panel_id, "normal")}
              className="research-panel-btn"
            >
              ▢
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Minimize ${panel.title}`}
              title="Minimize"
              onClick={() => onState(panel.panel_id, "minimized")}
              className="research-panel-btn"
            >
              –
            </button>
          )}
          {panel.state === "maximized" ? (
            <button
              type="button"
              aria-label={`Restore ${panel.title} size`}
              title="Restore size"
              onClick={() => onState(panel.panel_id, "normal")}
              className="research-panel-btn"
            >
              ❐
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Maximize ${panel.title}`}
              title="Maximize"
              onClick={() => onState(panel.panel_id, "maximized")}
              className="research-panel-btn"
            >
              ⛶
            </button>
          )}
          <button
            type="button"
            aria-label={`Close ${panel.title}`}
            title="Close"
            onClick={() => onState(panel.panel_id, "closed")}
            className="research-panel-btn"
          >
            ×
          </button>
        </div>
      </header>
      {panel.state !== "minimized" && (
        <div className="research-panel-body">{children}</div>
      )}
    </article>
  );
}
