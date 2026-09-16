"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FloatingRect, PanelMutation, ResearchPanel } from "@/types/research";
import {
  clampRect,
  defaultRect,
  moveRect,
  resizeRect,
  type ResizeMode,
} from "../components/research/panelGeometry";

export interface ActiveGesture {
  type: "move" | "resize";
  panelId: string;
  pointerId: number;
  initialPointer: { x: number; y: number };
  initialRect: FloatingRect;
  initialScroll: { x: number; y: number };
  currentRect: FloatingRect;
  mode?: ResizeMode;
}

export interface UsePanelLayoutOptions {
  workspaceId: string;
  panels: ResearchPanel[];
  stageWidth: number;
  onSaveMutation?: (panelId: string, mutation: PanelMutation) => Promise<ResearchPanel | null>;
}

export function usePanelLayout({
  workspaceId,
  panels,
  stageWidth,
  onSaveMutation,
}: UsePanelLayoutOptions) {
  // Local transient overrides (optimistic & gesture state)
  const [localRects, setLocalRects] = useState<Record<string, FloatingRect>>({});
  const [localZIndices, setLocalZIndices] = useState<Record<string, number>>({});
  const [activeGesture, setActiveGesture] = useState<ActiveGesture | null>(null);
  const [activePanelId, setActivePanelId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const highestZRef = useRef(10);
  const activeGestureRef = useRef<ActiveGesture | null>(null);
  useEffect(() => {
    activeGestureRef.current = activeGesture;
  }, [activeGesture]);

  const [lastFailedMutation, setLastFailedMutation] = useState<{ panelId: string; mutation: PanelMutation } | null>(null);
  const mutationQueueRef = useRef<Promise<void>>(Promise.resolve());

  // Reset transient state when switching workspaces during render
  const [prevWorkspaceId, setPrevWorkspaceId] = useState(workspaceId);
  if (prevWorkspaceId !== workspaceId) {
    setPrevWorkspaceId(workspaceId);
    setActiveGesture(null);
    setActivePanelId(null);
    setSaveError(null);
    setLocalRects({});
    setLocalZIndices({});
    highestZRef.current = 10;
    setLastFailedMutation(null);
  }

  // Synchronize initial z_index and floating geometry from incoming panels
  useEffect(() => {
    let maxZ = highestZRef.current;
    panels.forEach((p, idx) => {
      const z = p.layout.z_index ?? idx + 1;
      if (z > maxZ) maxZ = z;
    });
    highestZRef.current = maxZ;
  }, [panels]);

  // Derive stable display rectangle for a panel
  const getPanelRect = useCallback(
    (panel: ResearchPanel, index: number): FloatingRect => {
      // If currently dragging, use transient gesture rect
      if (activeGesture && activeGesture.panelId === panel.panel_id) {
        return clampRect(activeGesture.currentRect, stageWidth);
      }
      // If optimistic local rectangle exists
      const local = localRects[panel.panel_id];
      if (local) {
        return clampRect(local, stageWidth);
      }
      // If persisted floating rectangle exists
      if (panel.layout.floating) {
        return clampRect(panel.layout.floating, stageWidth);
      }
      // Otherwise calculate default cascading rectangle
      return defaultRect(index, stageWidth, panel.layout.min_height);
    },
    [activeGesture, localRects, stageWidth]
  );

  // Derive display z-index for a panel
  const getPanelZIndex = useCallback(
    (panel: ResearchPanel, index: number): number => {
      if (localZIndices[panel.panel_id] !== undefined) {
        return localZIndices[panel.panel_id];
      }
      return panel.layout.z_index ?? index + 1;
    },
    [localZIndices]
  );

  // Serialized mutation dispatcher
  const queueMutation = useCallback(
    (panelId: string, mutation: PanelMutation) => {
      if (!onSaveMutation) return;

      mutationQueueRef.current = mutationQueueRef.current
        .then(async () => {
          try {
            const updated = await onSaveMutation(panelId, mutation);
            if (!updated) {
              setSaveError("Layout not saved");
              setLastFailedMutation({ panelId, mutation });
            } else {
              setSaveError(null);
              setLastFailedMutation(null);
            }
          } catch {
            setSaveError("Layout not saved");
            setLastFailedMutation({ panelId, mutation });
          }
        })
        .catch(() => {
          // Keep queue healthy
        });
    },
    [onSaveMutation]
  );

  // Bring a panel to front
  const bringToFront = useCallback(
    (panelId: string) => {
      const currentHighest = highestZRef.current;
      const panel = panels.find((p) => p.panel_id === panelId);
      const currentZ = localZIndices[panelId] ?? panel?.layout.z_index ?? 0;

      // Avoid redundant mutation if already frontmost
      if (currentZ >= currentHighest && activePanelId === panelId) {
        return;
      }

      const nextZ = currentHighest + 1;
      highestZRef.current = nextZ;
      setLocalZIndices((prev) => ({ ...prev, [panelId]: nextZ }));
      setActivePanelId(panelId);

      queueMutation(panelId, { bring_to_front: true });
    },
    [activePanelId, localZIndices, panels, queueMutation]
  );

  // Start Move Gesture
  const startMove = useCallback(
    (panelId: string, e: React.PointerEvent, initialRect: FloatingRect) => {
      e.preventDefault();
      bringToFront(panelId);

      const target = e.currentTarget;
      target.setPointerCapture?.(e.pointerId);

      const gesture: ActiveGesture = {
        type: "move",
        panelId,
        pointerId: e.pointerId,
        initialPointer: { x: e.clientX, y: e.clientY },
        initialRect,
        initialScroll: {
          x: typeof window !== "undefined" ? window.scrollX : 0,
          y: typeof window !== "undefined" ? window.scrollY : 0,
        },
        currentRect: initialRect,
      };

      setActiveGesture(gesture);

      const handlePointerMove = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        const dx = ev.clientX - gesture.initialPointer.x;
        const dy = ev.clientY - gesture.initialPointer.y;
        const updated = moveRect(gesture.initialRect, dx, dy, stageWidth);
        setActiveGesture((prev) => (prev ? { ...prev, currentRect: updated } : null));
      };

      const handlePointerUp = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        cleanup();
        const active = activeGestureRef.current;
        if (active && active.panelId === panelId) {
          const finalRect = active.currentRect;
          setLocalRects((prev) => ({ ...prev, [panelId]: finalRect }));
          queueMutation(panelId, { floating: finalRect });
        }
        setActiveGesture(null);
      };

      const handleCancel = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        cleanup();
        setActiveGesture(null);
      };

      const handleKeyDown = (ke: KeyboardEvent) => {
        if (ke.key === "Escape") {
          cleanup();
          setActiveGesture(null);
        }
      };

      const cleanup = () => {
        try {
          target.releasePointerCapture?.(e.pointerId);
        } catch {
          // Pointer capture may have already been released
        }
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
        window.removeEventListener("pointercancel", handleCancel);
        window.removeEventListener("keydown", handleKeyDown);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
      window.addEventListener("pointercancel", handleCancel);
      window.addEventListener("keydown", handleKeyDown);
    },
    [bringToFront, queueMutation, stageWidth]
  );

  // Start Resize Gesture
  const startResize = useCallback(
    (
      panelId: string,
      mode: ResizeMode,
      e: React.PointerEvent,
      initialRect: FloatingRect
    ) => {
      e.preventDefault();
      e.stopPropagation();
      bringToFront(panelId);

      const target = e.currentTarget;
      target.setPointerCapture?.(e.pointerId);

      const gesture: ActiveGesture = {
        type: "resize",
        panelId,
        pointerId: e.pointerId,
        initialPointer: { x: e.clientX, y: e.clientY },
        initialRect,
        initialScroll: {
          x: typeof window !== "undefined" ? window.scrollX : 0,
          y: typeof window !== "undefined" ? window.scrollY : 0,
        },
        currentRect: initialRect,
        mode,
      };

      setActiveGesture(gesture);

      const handlePointerMove = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        const dx = ev.clientX - gesture.initialPointer.x;
        const dy = ev.clientY - gesture.initialPointer.y;
        const updated = resizeRect(gesture.initialRect, dx, dy, mode, stageWidth);
        setActiveGesture((prev) => (prev ? { ...prev, currentRect: updated } : null));
      };

      const handlePointerUp = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        cleanup();
        const active = activeGestureRef.current;
        if (active && active.panelId === panelId) {
          const finalRect = active.currentRect;
          setLocalRects((prev) => ({ ...prev, [panelId]: finalRect }));
          queueMutation(panelId, { floating: finalRect });
        }
        setActiveGesture(null);
      };

      const handleCancel = (ev: PointerEvent) => {
        if (ev.pointerId !== gesture.pointerId) return;
        cleanup();
        setActiveGesture(null);
      };

      const handleKeyDown = (ke: KeyboardEvent) => {
        if (ke.key === "Escape") {
          cleanup();
          setActiveGesture(null);
        }
      };

      const cleanup = () => {
        try {
          target.releasePointerCapture?.(e.pointerId);
        } catch {
          // Ignore
        }
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
        window.removeEventListener("pointercancel", handleCancel);
        window.removeEventListener("keydown", handleKeyDown);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
      window.addEventListener("pointercancel", handleCancel);
      window.addEventListener("keydown", handleKeyDown);
    },
    [bringToFront, queueMutation, stageWidth]
  );

  // Keyboard move (16px increment)
  const moveWithKeyboard = useCallback(
    (panelId: string, key: string, currentRect: FloatingRect) => {
      let dx = 0;
      let dy = 0;
      if (key === "ArrowLeft") dx = -16;
      else if (key === "ArrowRight") dx = 16;
      else if (key === "ArrowUp") dy = -16;
      else if (key === "ArrowDown") dy = 16;
      else return;

      const nextRect = moveRect(currentRect, dx, dy, stageWidth);
      setLocalRects((prev) => ({ ...prev, [panelId]: nextRect }));
      queueMutation(panelId, { floating: nextRect });
    },
    [queueMutation, stageWidth]
  );

  // Keyboard resize (16px increment)
  const resizeWithKeyboard = useCallback(
    (panelId: string, mode: ResizeMode, key: string, currentRect: FloatingRect) => {
      let dx = 0;
      let dy = 0;
      if (key === "ArrowUp") dy = -16;
      else if (key === "ArrowDown") dy = 16;
      else if (key === "ArrowLeft" && mode === "both") dx = -16;
      else if (key === "ArrowRight" && mode === "both") dx = 16;
      else return;

      const nextRect = resizeRect(currentRect, dx, dy, mode, stageWidth);
      setLocalRects((prev) => ({ ...prev, [panelId]: nextRect }));
      queueMutation(panelId, { floating: nextRect });
    },
    [queueMutation, stageWidth]
  );

  // Reset layout for this workspace
  const resetLayout = useCallback(() => {
    setLocalRects({});
    panels.forEach((p, idx) => {
      const resetR = defaultRect(idx, stageWidth, p.layout.min_height);
      queueMutation(p.panel_id, { floating: resetR, bring_to_front: true });
    });
  }, [panels, queueMutation, stageWidth]);

  // Retry last failed save
  const retryLastSave = useCallback(() => {
    if (lastFailedMutation) {
      queueMutation(lastFailedMutation.panelId, lastFailedMutation.mutation);
    }
  }, [lastFailedMutation, queueMutation]);

  return {
    getPanelRect,
    getPanelZIndex,
    activePanelId,
    activeGesture,
    bringToFront,
    startMove,
    startResize,
    moveWithKeyboard,
    resizeWithKeyboard,
    resetLayout,
    saveError,
    retryLastSave,
  };
}
