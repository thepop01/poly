"use client";

import { useState } from "react";
import type { PanelLayout, PanelType, ResearchPanel } from "@/types/research";
import PanelFrame from "./PanelFrame";
import { PanelRenderer } from "./PanelRenderer";

export const PANEL_DEFAULTS: Record<PanelType, Pick<PanelLayout, "col_span" | "min_height">> = {
  wallet_table: { col_span: 6, min_height: 380 },
  market_table: { col_span: 6, min_height: 380 },
  overlap_table: { col_span: 6, min_height: 380 },
  consensus: { col_span: 6, min_height: 380 },
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
  const [spanOverrides, setSpanOverrides] = useState<Record<string, number>>({});
  const [orderOverrides, setOrderOverrides] = useState<string[]>([]);
  const [draggedId, setDraggedId] = useState<string | null>(null);

  const unclosed = panels.filter((p) => p.state !== "closed");
  const closed = ordered(panels.filter((p) => p.state === "closed"));

  // Sort visible panels according to orderOverrides if present
  const defaultSorted = ordered(unclosed);
  const visible = orderOverrides.length > 0
    ? [...unclosed].sort((a, b) => {
        const idxA = orderOverrides.indexOf(a.panel_id);
        const idxB = orderOverrides.indexOf(b.panel_id);
        if (idxA !== -1 && idxB !== -1) return idxA - idxB;
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return defaultSorted.indexOf(a) - defaultSorted.indexOf(b);
      })
    : defaultSorted;

  const maximized = visible.find((p) => p.state === "maximized");
  const shown = maximized ? [maximized] : visible;

  const handleResizeSpan = (panelId: string, span: number) => {
    setSpanOverrides((prev) => ({
      ...prev,
      [panelId]: span,
    }));
  };

  const handleMove = (panelId: string, direction: "prev" | "next") => {
    const currentIds = visible.map((p) => p.panel_id);
    const index = currentIds.indexOf(panelId);
    if (index === -1) return;
    const targetIndex = direction === "prev" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= currentIds.length) return;
    const nextIds = [...currentIds];
    const [moved] = nextIds.splice(index, 1);
    nextIds.splice(targetIndex, 0, moved);
    setPanelOrderOverrides(nextIds);
  };

  const setPanelOrderOverrides = (nextIds: string[]) => {
    setOrderOverrides(nextIds);
  };

  const handleDragStart = (panelId: string) => {
    setDraggedId(panelId);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (targetId: string) => {
    if (!draggedId || draggedId === targetId) return;
    const currentIds = visible.map((p) => p.panel_id);
    const fromIndex = currentIds.indexOf(draggedId);
    const toIndex = currentIds.indexOf(targetId);
    if (fromIndex === -1 || toIndex === -1) return;
    const nextIds = [...currentIds];
    const [moved] = nextIds.splice(fromIndex, 1);
    nextIds.splice(toIndex, 0, moved);
    setPanelOrderOverrides(nextIds);
    setDraggedId(null);
  };

  return (
    <div className="research-canvas-body" data-testid="panel-canvas">
      {visible.length === 0 && closed.length === 0 ? (
        <p className="px-6 py-10 text-center text-sm text-subtle">
          Run an analysis to populate this canvas with evidence panels.
        </p>
      ) : (
        <div className="research-panel-grid">
          {shown.map((panel, idx) => {
            const colSpan = spanOverrides[panel.panel_id] ?? (panel.layout.col_span === 12 ? 6 : panel.layout.col_span);
            const canMovePrev = idx > 0;
            const canMoveNext = idx < shown.length - 1;

            return (
              <div
                key={panel.panel_id}
                className={`research-span-${colSpan} transition-all duration-200`}
                onDragOver={handleDragOver}
                onDrop={() => handleDrop(panel.panel_id)}
              >
                <PanelFrame
                  panel={panel}
                  colSpan={colSpan}
                  onResizeSpan={(span) => handleResizeSpan(panel.panel_id, span)}
                  onToggleSpan={() => handleResizeSpan(panel.panel_id, colSpan === 12 ? 6 : 12)}
                  onMove={(dir) => handleMove(panel.panel_id, dir)}
                  canMovePrev={canMovePrev}
                  canMoveNext={canMoveNext}
                  onDragStart={() => handleDragStart(panel.panel_id)}
                  isDragging={draggedId === panel.panel_id}
                  onState={onPanelState}
                >
                  <PanelRenderer panel={panel} />
                </PanelFrame>
              </div>
            );
          })}
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
