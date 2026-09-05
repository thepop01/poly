"use client";

import type { PanelLayout, PanelType, ResearchPanel } from "@/types/research";
import PanelFrame from "./PanelFrame";
import { PanelRenderer } from "./PanelRenderer";

export const PANEL_DEFAULTS: Record<PanelType, Pick<PanelLayout, "col_span" | "min_height">> = {
  wallet_table: { col_span: 12, min_height: 420 },
  market_table: { col_span: 12, min_height: 420 },
  overlap_table: { col_span: 8, min_height: 380 },
  consensus: { col_span: 4, min_height: 380 },
};

interface PanelCanvasProps {
  panels: ResearchPanel[];
  onPanelState: (panelId: string, state: ResearchPanel["state"]) => void;
}

function ordered(panels: ResearchPanel[]): ResearchPanel[] {
  return [...panels].sort((a, b) => {
    if (a.layout.order !== b.layout.order) return a.layout.order - b.layout.order;
    return a.created_at.localeCompare(b.created_at);
  });
}

export default function PanelCanvas({ panels, onPanelState }: PanelCanvasProps) {
  const visible = ordered(panels.filter((p) => p.state !== "closed"));
  const closed = ordered(panels.filter((p) => p.state === "closed"));
  const maximized = visible.find((p) => p.state === "maximized");
  const shown = maximized ? [maximized] : visible;

  return (
    <div className="research-canvas-body" data-testid="panel-canvas">
      {visible.length === 0 && closed.length === 0 ? (
        <p className="px-6 py-10 text-center text-sm text-subtle">
          Run an analysis to populate this canvas with evidence panels.
        </p>
      ) : (
        <div className="research-panel-grid">
          {shown.map((panel) => (
            <div
              key={panel.panel_id}
              className={`research-span-${panel.layout.col_span}`}
              style={{ minHeight: panel.layout.min_height }}
            >
              <PanelFrame panel={panel} onState={onPanelState}>
                <PanelRenderer panel={panel} />
              </PanelFrame>
            </div>
          ))}
        </div>
      )}
      {closed.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-2" aria-label="Closed panels">
          <span className="text-xs text-subtle">Closed:</span>
          {closed.map((panel) => (
            <button
              key={panel.panel_id}
              type="button"
              onClick={() => onPanelState(panel.panel_id, "normal")}
              className="rounded-md border border-border bg-surface px-2 py-0.5 text-xs hover:bg-surface-2"
            >
              Restore {panel.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
