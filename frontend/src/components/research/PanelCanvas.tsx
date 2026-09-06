"use client";

import { useEffect, useRef, useState } from "react";
import { LayoutGrid } from "lucide-react";
import type { PanelLayout, PanelMutation, PanelType, ResearchPanel } from "@/types/research";
import PanelFrame from "./PanelFrame";
import { PanelRenderer } from "./PanelRenderer";
import { usePanelLayout } from "@/hooks/usePanelLayout";

export const PANEL_DEFAULTS: Record<PanelType, Pick<PanelLayout, "col_span" | "min_height">> = {
  wallet_table: { col_span: 6, min_height: 380 },
  market_table: { col_span: 6, min_height: 380 },
  overlap_table: { col_span: 6, min_height: 380 },
  consensus: { col_span: 6, min_height: 380 },
};

interface PanelCanvasProps {
  workspaceId?: string | null;
  panels: ResearchPanel[];
  onPanelState: (panelId: string, state: ResearchPanel["state"]) => void;
  onSaveMutation?: (panelId: string, mutation: PanelMutation) => Promise<ResearchPanel | null>;
}

export default function PanelCanvas({
  workspaceId,
  panels,
  onPanelState,
  onSaveMutation,
}: PanelCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageWidth, setStageWidth] = useState(1200);
  const [containerHeight, setContainerHeight] = useState(600);
  const [isDesktop, setIsDesktop] = useState(true);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateSize = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0) {
        setStageWidth(Math.floor(rect.width));
        setContainerHeight(Math.floor(rect.height));
      }
      const desktop =
        (rect.width === 0 || rect.width >= 640) &&
        (typeof window === "undefined" || window.innerWidth >= 768);
      setIsDesktop(desktop);
    };
    updateSize();

    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => updateSize());
      ro.observe(el);
      window.addEventListener("resize", updateSize);
      return () => {
        ro.disconnect();
        window.removeEventListener("resize", updateSize);
      };
    }
    window.addEventListener("resize", updateSize);
    return () => {
      window.removeEventListener("resize", updateSize);
    };
  }, []);

  const layout = usePanelLayout({
    workspaceId: workspaceId ?? "default",
    panels,
    stageWidth,
    onSaveMutation:
      onSaveMutation ??
      (async (panelId, mutation) => {
        if (mutation.state) {
          onPanelState(panelId, mutation.state);
        }
        return null;
      }),
  });

  const unclosed = panels.filter((p) => p.state !== "closed");
  const closed = panels.filter((p) => p.state === "closed");
  const maximized = unclosed.find((p) => p.state === "maximized");
  const shown = maximized ? [maximized] : unclosed;

  return (
    <div
      ref={containerRef}
      className="research-canvas-body relative w-full h-full min-h-[400px]"
      data-testid="panel-canvas"
    >
      {isDesktop && (
        <div
          className="research-canvas-toolbar mb-2 flex items-center justify-end"
          data-testid="canvas-toolbar"
        >
          <button
            type="button"
            onClick={layout.resetLayout}
            className="research-canvas-align-btn flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-surface/80 hover:bg-surface-2 border border-border text-foreground transition-colors cursor-pointer shadow-xs"
            title="Reset panel positions to cascade layout"
            data-testid="reset-layout-btn"
          >
            <LayoutGrid size={12} className="text-subtle" />
            <span>Reset layout</span>
          </button>
        </div>
      )}

      {layout.saveError && (
        <div
          role="alert"
          className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400"
          data-testid="layout-save-error"
        >
          <span>Failed to save panel layout.</span>
          <button
            type="button"
            onClick={layout.retryLastSave}
            className="rounded bg-red-500/20 px-2 py-0.5 font-medium hover:bg-red-500/30 text-red-200 cursor-pointer"
          >
            Retry
          </button>
        </div>
      )}

      {visibleContent(shown, closed, isDesktop, layout, stageWidth, containerHeight, onPanelState)}

      {closed.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-2 px-4 py-2 mt-4"
          aria-label="Closed panels"
        >
          <span className="text-xs text-subtle">Closed:</span>
          {closed.map((panel) => (
            <button
              key={panel.panel_id}
              type="button"
              onClick={() => onPanelState(panel.panel_id, "normal")}
              className="rounded-md border border-border bg-surface px-2 py-0.5 text-xs hover:bg-surface-2 text-foreground cursor-pointer"
            >
              Restore {panel.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function visibleContent(
  shown: ResearchPanel[],
  closed: ResearchPanel[],
  isDesktop: boolean,
  layout: ReturnType<typeof usePanelLayout>,
  stageWidth: number,
  containerHeight: number,
  onPanelState: (panelId: string, state: ResearchPanel["state"]) => void,
) {
  if (shown.length === 0 && closed.length === 0) {
    return (
      <p className="px-6 py-10 text-center text-sm text-subtle">
        Run an analysis to populate this canvas with evidence panels.
      </p>
    );
  }

  if (!isDesktop) {
    return (
      <div className="flex flex-col gap-4 w-full" data-testid="stacked-canvas">
        {shown.map((panel) => (
          <div key={panel.panel_id} className="w-full">
            <PanelFrame
              panel={panel}
              isActive={layout.activePanelId === panel.panel_id}
              onBringToFront={() => layout.bringToFront(panel.panel_id)}
              onState={onPanelState}
            >
              <PanelRenderer panel={panel} />
            </PanelFrame>
          </div>
        ))}
      </div>
    );
  }

  // Compute stage height dynamically from panel positions
  const maxBottom = shown.reduce((acc, p, idx) => {
    const r = layout.getPanelRect(p, idx);
    return Math.max(acc, r.y + r.height);
  }, 500);
  const stageHeight = Math.max(containerHeight, maxBottom + 48);

  return (
    <div
      className="research-canvas-stage relative w-full"
      style={{ height: `${stageHeight}px`, minHeight: "100%" }}
      data-testid="floating-stage"
    >
      {shown.map((panel, idx) => {
        const isMax = panel.state === "maximized";
        const r = isMax
          ? { x: 0, y: 0, width: stageWidth, height: Math.max(containerHeight, 600) }
          : layout.getPanelRect(panel, idx);
        const zIndex = isMax ? 9999 : layout.getPanelZIndex(panel, idx);
        const isActive = layout.activePanelId === panel.panel_id;
        const isMoving =
          layout.activeGesture?.type === "move" &&
          layout.activeGesture.panelId === panel.panel_id;
        const isResizing =
          layout.activeGesture?.type === "resize" &&
          layout.activeGesture.panelId === panel.panel_id;

        return (
          <div
            key={panel.panel_id}
            className="research-panel-floating absolute"
            style={{
              transform: `translate3d(${r.x}px, ${r.y}px, 0)`,
              width: `${r.width}px`,
              height: `${r.height}px`,
              zIndex,
              willChange: isMoving || isResizing ? "transform, width, height" : "auto",
            }}
            onPointerDown={() => layout.bringToFront(panel.panel_id)}
          >
            <PanelFrame
              panel={panel}
              isActive={isActive}
              onBringToFront={() => layout.bringToFront(panel.panel_id)}
              onStartMove={(e) => layout.startMove(panel.panel_id, e, r)}
              onStartResize={(mode, e) => layout.startResize(panel.panel_id, mode, e, r)}
              onMoveKeyboard={(key) => layout.moveWithKeyboard(panel.panel_id, key, r)}
              onResizeKeyboard={(mode, key) => layout.resizeWithKeyboard(panel.panel_id, mode, key, r)}
              onState={onPanelState}
            >
              <PanelRenderer panel={panel} />
            </PanelFrame>
          </div>
        );
      })}
    </div>
  );
}
