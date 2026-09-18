import type { FloatingRect } from "@/types/research";

export type ResizeMode = "height" | "width" | "both";

export const MIN_PANEL_WIDTH = 320;
export const MIN_PANEL_HEIGHT = 240;
export const MAX_PANEL_DIMENSION = 4096;
export const MAX_STAGE_HEIGHT = 100_000;
export const DEFAULT_CASCADE_STEP = 24;

export function clampRect(rect: FloatingRect, stageWidth: number): FloatingRect {
  const safeStageWidth = Math.max(0, Math.round(stageWidth));
  const w = Math.min(
    MAX_PANEL_DIMENSION,
    Math.max(Math.min(MIN_PANEL_WIDTH, safeStageWidth), Math.min(rect.width, safeStageWidth))
  );
  const maxH = Math.min(MAX_PANEL_DIMENSION, MAX_STAGE_HEIGHT);
  const h = Math.max(MIN_PANEL_HEIGHT, Math.min(rect.height, maxH));
  const maxX = Math.max(0, safeStageWidth - w);
  const maxY = Math.max(0, MAX_STAGE_HEIGHT - h);
  const x = Math.max(0, Math.min(rect.x, maxX));
  const y = Math.max(0, Math.min(rect.y, maxY));
  return { x, y, width: w, height: h };
}

export function moveRect(
  rect: FloatingRect,
  dx: number,
  dy: number,
  stageWidth: number
): FloatingRect {
  const safeStageWidth = Math.max(0, Math.round(stageWidth));
  const targetX = rect.x + Math.round(dx);
  const targetY = rect.y + Math.round(dy);
  const maxX = Math.max(0, safeStageWidth - rect.width);
  const maxY = Math.max(0, MAX_STAGE_HEIGHT - rect.height);
  const x = Math.max(0, Math.min(targetX, maxX));
  const y = Math.max(0, Math.min(targetY, maxY));
  return { x, y, width: rect.width, height: rect.height };
}

export function resizeRect(
  rect: FloatingRect,
  dx: number,
  dy: number,
  mode: ResizeMode,
  stageWidth: number
): FloatingRect {
  const safeStageWidth = Math.max(0, Math.round(stageWidth));
  const deltaY = Math.round(dy);
  const deltaX = Math.round(dx);

  let height = rect.height;
  if (mode === "height" || mode === "both") {
    height = Math.max(
      MIN_PANEL_HEIGHT,
      Math.min(rect.height + deltaY, MAX_PANEL_DIMENSION)
    );
    if (rect.y + height > MAX_STAGE_HEIGHT) {
      height = Math.max(0, MAX_STAGE_HEIGHT - rect.y);
    }
  }

  if (mode === "height") {
    return { x: rect.x, y: rect.y, width: rect.width, height };
  }

  const maxWidth = Math.max(0, Math.min(MAX_PANEL_DIMENSION, safeStageWidth - rect.x));
  const targetWidth = rect.width + deltaX;
  const width = Math.max(
    Math.min(MIN_PANEL_WIDTH, maxWidth),
    Math.min(targetWidth, maxWidth)
  );

  return { x: rect.x, y: rect.y, width, height };
}

export function defaultRect(
  index: number,
  stageWidth: number,
  minHeight: number
): FloatingRect {
  const safeStageWidth = Math.max(0, Math.round(stageWidth));
  const width = Math.min(560, safeStageWidth);
  const height = Math.max(MIN_PANEL_HEIGHT, Math.min(minHeight || 380, MAX_PANEL_DIMENSION));

  const maxStartX = Math.max(0, safeStageWidth - width);
  let x = index * DEFAULT_CASCADE_STEP;
  if (maxStartX > 0 && x > maxStartX) {
    x = (index * DEFAULT_CASCADE_STEP) % (maxStartX + 1);
  } else if (maxStartX === 0) {
    x = 0;
  }

  const y = index * DEFAULT_CASCADE_STEP;
  return { x, y, width, height };
}
