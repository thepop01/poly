import { describe, expect, it } from "vitest";
import {
  clampRect,
  defaultRect,
  moveRect,
  resizeRect,
} from "../panelGeometry";

describe("panelGeometry", () => {
  it("resizes height only and corner both axes", () => {
    const rect = { x: 20, y: 30, width: 400, height: 300 };
    expect(resizeRect(rect, 90, 100, "height", 1000)).toEqual({
      x: 20,
      y: 30,
      width: 400,
      height: 400,
    });
    expect(resizeRect(rect, 50, 100, "both", 1000)).toEqual({
      x: 20,
      y: 30,
      width: 450,
      height: 400,
    });
    expect(resizeRect(rect, 80, 100, "width", 1000)).toEqual({
      x: 20,
      y: 30,
      width: 480,
      height: 300,
    });
    expect(resizeRect(rect, 0, -900, "height", 1000).height).toBe(240);
    expect(resizeRect(rect, -900, 0, "both", 1000).width).toBe(320);
    expect(resizeRect(rect, -900, 0, "width", 1000).width).toBe(320);
  });

  it("moves rect with bounds enforcement", () => {
    const rect = { x: 20, y: 30, width: 400, height: 300 };
    expect(moveRect(rect, -100, -100, 1000)).toEqual({
      x: 0,
      y: 0,
      width: 400,
      height: 300,
    });
    expect(moveRect(rect, 900, 0, 1000).x).toBe(600);
    expect(moveRect(rect, 0, 150000, 1000).y).toBe(100000 - 300);
  });

  it("clamps rect when stage narrows without mutating original", () => {
    const rect = { x: 600, y: 50, width: 500, height: 400 };
    const clamped = clampRect(rect, 800);
    expect(clamped.width).toBe(500);
    expect(clamped.x).toBe(300); // 800 - 500 = 300
    expect(rect.x).toBe(600); // immutable
  });

  it("calculates default cascading rects", () => {
    const r0 = defaultRect(0, 1200, 420);
    expect(r0).toEqual({ x: 0, y: 0, width: 560, height: 420 });

    const r1 = defaultRect(1, 1200, 420);
    expect(r1).toEqual({ x: 24, y: 24, width: 560, height: 420 });

    const rNarrow = defaultRect(0, 400, 300);
    expect(rNarrow.width).toBe(400);
    expect(rNarrow.height).toBe(300);
  });

  it("enforces maximum size bound of 4096 and stage height cap of 100000", () => {
    const rect = { x: 0, y: 0, width: 4000, height: 4000 };
    const oversized = resizeRect(rect, 500, 500, "both", 10000);
    expect(oversized.width).toBe(4096);
    expect(oversized.height).toBe(4096);

    const nearBottom = { x: 0, y: 99800, width: 400, height: 300 };
    const hitBottom = resizeRect(nearBottom, 0, 500, "height", 1000);
    expect(hitBottom.height).toBe(200); // 100000 - 99800 = 200, but clamped >= 200 or max height
  });
});
