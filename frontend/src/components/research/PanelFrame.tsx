"use client";

import type { ResearchPanel } from "@/types/research";
import { Minimize2, Maximize2, X, RotateCcw, Table2, BarChart2, Users, Layers, Columns2 } from "lucide-react";

interface PanelFrameProps {
  panel: ResearchPanel;
  colSpan?: number;
  onToggleSpan?: () => void;
  hidden?: boolean;
  onState: (panelId: string, state: ResearchPanel["state"]) => void;
  children: React.ReactNode;
}

const PANEL_TYPE_CONFIG: Record<
  string,
  { icon: React.ComponentType<{ size?: number; className?: string }>; accent: string; label: string }
> = {
  wallet_table:  { icon: Users,    accent: "#059669", label: "Wallets" },
  market_table:  { icon: BarChart2, accent: "#7C3AED", label: "Markets" },
  overlap_table: { icon: Layers,    accent: "#0284C7", label: "Overlap" },
  consensus:     { icon: Table2,    accent: "#D97706", label: "Consensus" },
};

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
  if (typeof config.row_count === "number") parts.push(`${config.row_count.toLocaleString()} rows`);
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

function isLive(panel: ResearchPanel): boolean {
  const config = panel.config as { snapshot_at?: string; live?: boolean };
  if (config.live) return true;
  if (!config.snapshot_at) return false;
  const snapAge = Date.now() - new Date(config.snapshot_at).getTime();
  return snapAge < 5 * 60 * 1000; // within 5 minutes = "live"
}

export default function PanelFrame({
  panel,
  colSpan,
  onToggleSpan,
  hidden,
  onState,
  children,
}: PanelFrameProps) {
  const meta = metaLine(panel);
  const typeConfig = PANEL_TYPE_CONFIG[panel.panel_type] ?? { icon: Table2, accent: "#64748B", label: panel.panel_type };
  const TypeIcon = typeConfig.icon;
  const live = isLive(panel);
  const minimized = panel.state === "minimized";
  const maximized = panel.state === "maximized";

  return (
    <article
      aria-label={panel.title}
      data-testid={`panel-${panel.panel_id}`}
      data-panel-type={panel.panel_type}
      className={`research-panel${minimized ? " research-panel-minimized" : ""} ${maximized ? "research-panel-maximized" : ""}`}
      hidden={hidden}
    >
      {/* Colored accent strip at top */}
      <div
        className="research-panel-accent-strip"
        style={{ backgroundColor: typeConfig.accent }}
        aria-hidden="true"
      />

      <header className="research-panel-header">
        {/* Left: icon chip + title + meta */}
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="research-panel-type-icon"
            style={{ color: typeConfig.accent, backgroundColor: `${typeConfig.accent}18` }}
          >
            <TypeIcon size={12} />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-foreground">{panel.title}</h3>
            {meta && <p className="truncate text-[11px] text-subtle">{meta}</p>}
          </div>
        </div>

        {/* Right: live badge + controls */}
        <div className="flex flex-shrink-0 items-center gap-1.5">
          {/* Live / Snapshot badge */}
          {live ? (
            <span className="research-panel-live-badge">
              <span className="research-panel-live-dot" />
              LIVE
            </span>
          ) : (
            <span className="research-panel-snapshot-badge">
              {typeConfig.label}
            </span>
          )}

          {/* Minimize / Restore */}
          {minimized ? (
            <button
              type="button"
              aria-label={`Restore ${panel.title}`}
              title="Restore"
              onClick={() => onState(panel.panel_id, "normal")}
              className="research-panel-btn"
            >
              <RotateCcw size={12} />
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Minimize ${panel.title}`}
              title="Minimize"
              onClick={() => onState(panel.panel_id, "minimized")}
              className="research-panel-btn"
            >
              <Minimize2 size={12} />
            </button>
          )}

          {/* Half / Full width toggle */}
          {onToggleSpan && !maximized && !minimized && (
            <button
              type="button"
              aria-label={colSpan === 12 ? `Split ${panel.title} to half width` : `Expand ${panel.title} to full width`}
              title={colSpan === 12 ? "Half width (side-by-side)" : "Full width"}
              onClick={onToggleSpan}
              className="research-panel-btn"
            >
              <Columns2 size={12} className={colSpan === 6 ? "text-primary" : ""} />
            </button>
          )}

          {/* Maximize / Restore size */}
          {maximized ? (
            <button
              type="button"
              aria-label={`Restore ${panel.title} size`}
              title="Restore size"
              onClick={() => onState(panel.panel_id, "normal")}
              className="research-panel-btn"
            >
              <Minimize2 size={12} />
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Maximize ${panel.title}`}
              title="Maximize"
              onClick={() => onState(panel.panel_id, "maximized")}
              className="research-panel-btn"
            >
              <Maximize2 size={12} />
            </button>
          )}

          {/* Close */}
          <button
            type="button"
            aria-label={`Close ${panel.title}`}
            title="Close"
            onClick={() => onState(panel.panel_id, "closed")}
            className="research-panel-btn research-panel-btn-close"
          >
            <X size={12} />
          </button>
        </div>
      </header>

      {!minimized && (
        <div className="research-panel-body">{children}</div>
      )}
    </article>
  );
}
