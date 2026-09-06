import { describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePanelLayout } from "./usePanelLayout";
import type { ResearchPanel } from "@/types/research";

function mockPanel(id = "p1", overrides: Partial<ResearchPanel> = {}): ResearchPanel {
  return {
    panel_id: id,
    workspace_id: "workspace-1",
    source_chat_id: "chat-1",
    result_set_id: null,
    panel_type: "wallet_table",
    panel_key: `key-${id}`,
    title: `Panel ${id}`,
    state: "normal",
    layout: { col_span: 6, min_height: 380, order: 0 },
    config: {},
    created_at: "2026-09-02T10:00:00Z",
    updated_at: "2026-09-02T10:00:00Z",
    ...overrides,
  };
}

describe("usePanelLayout", () => {
  it("computes default cascading rectangles when panels have no saved geometry", () => {
    const panels = [mockPanel("p1"), mockPanel("p2")];
    const { result } = renderHook(() =>
      usePanelLayout({
        workspaceId: "workspace-1",
        panels,
        stageWidth: 1200,
      })
    );

    const r0 = result.current.getPanelRect(panels[0], 0);
    const r1 = result.current.getPanelRect(panels[1], 1);

    expect(r0.x).toBe(0);
    expect(r0.y).toBe(0);
    expect(r1.x).toBe(24);
    expect(r1.y).toBe(24);
  });

  it("brings panel to front and queues mutation with bring_to_front: true", async () => {
    const panels = [mockPanel("p1"), mockPanel("p2")];
    const onSave = vi.fn().mockResolvedValue(panels[0]);

    const { result } = renderHook(() =>
      usePanelLayout({
        workspaceId: "workspace-1",
        panels,
        stageWidth: 1200,
        onSaveMutation: onSave,
      })
    );

    await act(async () => {
      result.current.bringToFront("p1");
      await Promise.resolve();
    });

    expect(result.current.activePanelId).toBe("p1");
    expect(result.current.getPanelZIndex(panels[0], 0)).toBeGreaterThan(
      result.current.getPanelZIndex(panels[1], 1)
    );
    expect(onSave).toHaveBeenCalledWith("p1", { bring_to_front: true });
  });

  it("does not queue redundant bring_to_front if panel is already active and frontmost", async () => {
    const panels = [mockPanel("p1", { layout: { col_span: 6, min_height: 380, order: 0, z_index: 99 } })];
    const onSave = vi.fn().mockResolvedValue(panels[0]);

    const { result } = renderHook(() =>
      usePanelLayout({
        workspaceId: "workspace-1",
        panels,
        stageWidth: 1200,
        onSaveMutation: onSave,
      })
    );

    // Initial activation
    await act(async () => {
      result.current.bringToFront("p1");
      await Promise.resolve();
    });
    expect(onSave).toHaveBeenCalledTimes(1);

    // Second activation on already frontmost panel is no-op
    await act(async () => {
      result.current.bringToFront("p1");
      await Promise.resolve();
    });
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("handles keyboard movement and queues mutation", async () => {
    const panels = [mockPanel("p1")];
    const onSave = vi.fn().mockResolvedValue(panels[0]);

    const { result } = renderHook(() =>
      usePanelLayout({
        workspaceId: "workspace-1",
        panels,
        stageWidth: 1200,
        onSaveMutation: onSave,
      })
    );

    const initial = result.current.getPanelRect(panels[0], 0);
    await act(async () => {
      result.current.moveWithKeyboard("p1", "ArrowRight", initial);
      await Promise.resolve();
    });

    const moved = result.current.getPanelRect(panels[0], 0);
    expect(moved.x).toBe(initial.x + 16);
    expect(onSave).toHaveBeenCalledWith("p1", { floating: moved });
  });

  it("resets transient layout state when workspace identity changes", async () => {
    const panels = [mockPanel("p1")];
    const onSave = vi.fn().mockResolvedValue(panels[0]);
    const { result, rerender } = renderHook(
      ({ workspaceId }) => usePanelLayout({ workspaceId, panels, stageWidth: 1200, onSaveMutation: onSave }),
      { initialProps: { workspaceId: "workspace-1" } },
    );
    act(() => result.current.bringToFront("p1"));
    expect(result.current.activePanelId).toBe("p1");
    rerender({ workspaceId: "workspace-2" });
    expect(result.current.activePanelId).toBeNull();
  });

  it("records save error on failed mutation and allows retry", async () => {
    const panels = [mockPanel("p1")];
    const onSave = vi.fn().mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() =>
      usePanelLayout({
        workspaceId: "workspace-1",
        panels,
        stageWidth: 1200,
        onSaveMutation: onSave,
      })
    );

    act(() => {
      result.current.bringToFront("p1");
    });

    // Wait for promise tick
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.saveError).toBe("Layout not saved");

    onSave.mockResolvedValueOnce(panels[0]);
    act(() => {
      result.current.retryLastSave();
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.saveError).toBeNull();
  });
});
