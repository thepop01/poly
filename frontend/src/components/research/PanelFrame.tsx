"use client";

import type { ResearchPanel } from "@/types/research";
import {
  Minus,
  Square,
  Minimize2,
  X,
  ChevronDown,
  Table2,
  BarChart2,
  Users,
  Layers,
  ArrowLeft,
  ArrowRight,
  GripVertical,
} from "lucide-react";

interface PanelFrameProps {
  panel: ResearchPanel;
  colSpan?: number;
  onResizeSpan?: (span: number) => void;
  onToggleSpan?: () => void;
  onMove?: (direction: "prev" | "next") => void;
  canMovePrev?: boolean;
  canMoveNext?: boolean;
  onDragStart?: () => void;
  isDragging?: boolean;
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
  onResizeSpan,
  onToggleSpan,
  onMove,
  canMovePrev,
  canMoveNext,
  onDragStart,
  isDragging,
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

  const handleSpanClick = (span: number) => {
    if (onResizeSpan) {
      onResizeSpan(span);
    } else if (onToggleSpan) {
      onToggleSpan();
    }
  };

  return (
    <article
      aria-label={panel.title}
      data-testid={`panel-${panel.panel_id}`}
      data-panel-type={panel.panel_type}
      className={`research-panel${minimized ? " research-panel-minimized" : ""} ${maximized ? "research-panel-maximized" : ""} ${isDragging ? "opacity-50" : ""}`}
      hidden={hidden}
    >
      {/* Colored accent strip at top */}
      <div
        className="research-panel-accent-strip"
        style={{ backgroundColor: typeConfig.accent }}
        aria-hidden="true"
      />

      <header className="research-panel-header">
        {/* Left: Move grip & arrows + icon chip + title + meta */}
        <div className="flex items-center gap-2 min-w-0">
          {onMove && !maximized && (
            <div className="flex items-center gap-0.5 text-subtle flex-shrink-0">
              <div
                draggable
                onDragStart={onDragStart}
                className="cursor-grab active:cursor-grabbing p-0.5 hover:text-foreground transition-colors"
                title="Drag to reorder panel"
                aria-label="Drag to reorder"
              >
                <GripVertical size={13} />
              </div>
              <button
                type="button"
                disabled={!canMovePrev}
                onClick={() => onMove("prev")}
                aria-label={`Move ${panel.title} left`}
                title="Move left / before"
                className="research-panel-move-btn disabled:opacity-20 disabled:cursor-not-allowed"
              >
                <ArrowLeft size={11} />
              </button>
              <button
                type="button"
                disabled={!canMoveNext}
                onClick={() => onMove("next")}
                aria-label={`Move ${panel.title} right`}
                title="Move right / after"
                className="research-panel-move-btn disabled:opacity-20 disabled:cursor-not-allowed"
              >
                <ArrowRight size={11} />
              </button>
            </div>
          )}

          <div
            className="research-panel-type-icon flex-shrink-0"
            style={{ color: typeConfig.accent, backgroundColor: `${typeConfig.accent}18` }}
          >
            <TypeIcon size={12} />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-foreground">{panel.title}</h3>
            {meta && <p className="truncate text-[11px] text-subtle">{meta}</p>}
          </div>
        </div>

        {/* Right: live badge + width presets + window controls */}
        <div className="flex flex-shrink-0 items-center gap-2">
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

          {/* Width Resizing Presets */}
          {!maximized && !minimized && (
            <div className="flex items-center bg-surface-2 border border-border rounded-md p-0.5 text-[10px] font-mono">
              {[
                { span: 6, label: "50%" },
                { span: 12, label: "100%" },
                { span: 4, label: "33%" },
                { span: 8, label: "66%" },
              ].map((opt) => (
                <button
                  key={opt.span}
                  type="button"
                  onClick={() => handleSpanClick(opt.span)}
                  aria-label={`Set ${panel.title} width to ${opt.label}`}
                  title={`Resize width to ${opt.label} (${opt.span} cols)`}
                  className={`px-1.5 py-0.5 rounded transition-colors cursor-pointer ${
                    colSpan === opt.span
                      ? "bg-primary text-white font-semibold shadow-xs"
                      : "text-subtle hover:text-foreground hover:bg-surface-3"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          {/* Window controls (Minimize [-], Maximize [□], Close [×]) */}
          <div className="flex items-center gap-1 border-l border-border pl-1.5">
            {/* Minimize / Restore */}
            <button
              type="button"
              aria-label={minimized ? `Restore ${panel.title}` : `Minimize ${panel.title}`}
              title={minimized ? "Restore panel" : "Minimize panel"}
              onClick={() => onState(panel.panel_id, minimized ? "normal" : "minimized")}
              className="research-panel-btn"
            >
              {minimized ? <ChevronDown size={12} /> : <Minus size={12} />}
            </button>

            {/* Maximize / Restore size */}
            <button
              type="button"
              aria-label={maximized ? `Restore ${panel.title} size` : `Maximize ${panel.title}`}
              title={maximized ? "Restore size" : "Maximize panel"}
              onClick={() => onState(panel.panel_id, maximized ? "normal" : "maximized")}
              className="research-panel-btn"
            >
              {maximized ? <Minimize2 size={11} /> : <Square size={11} strokeWidth={1.75} />}
            </button>

            {/* Close */}
            <button
              type="button"
              aria-label={`Close ${panel.title}`}
              title="Close panel"
              onClick={() => onState(panel.panel_id, "closed")}
              className="research-panel-btn research-panel-btn-close"
            >
              <X size={12} />
            </button>
          </div>
        </div>
      </header>

      {!minimized && (
        <div className="research-panel-body">{children}</div>
      )}
    </article>
  );
}
