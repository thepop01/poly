import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PanelFrame from "../PanelFrame";
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

describe("PanelFrame Interaction Handles", () => {
  it("renders move grip, bottom handle, and corner handle with proper accessibility labels", () => {
    const panel = mockPanel("1");
    const onStartMove = vi.fn();
    const onStartResize = vi.fn();

    render(
      <PanelFrame
        panel={panel}
        onState={vi.fn()}
        onStartMove={onStartMove}
        onStartResize={onStartResize}
      >
        <div>Content</div>
      </PanelFrame>
    );

    const moveGrip = screen.getByRole("button", { name: "Move Panel 1" });
    const bottomHandle = screen.getByRole("separator", { name: "Resize height of Panel 1" });
    const cornerHandle = screen.getByRole("separator", { name: "Resize Panel 1" });

    expect(moveGrip).toBeInTheDocument();
    expect(bottomHandle).toBeInTheDocument();
    expect(cornerHandle).toBeInTheDocument();
  });

  it("triggers onStartMove when dragging the header grip", () => {
    const panel = mockPanel("1");
    const onStartMove = vi.fn();

    render(
      <PanelFrame panel={panel} onState={vi.fn()} onStartMove={onStartMove}>
        <div>Content</div>
      </PanelFrame>
    );

    const moveGrip = screen.getByRole("button", { name: "Move Panel 1" });
    fireEvent.pointerDown(moveGrip, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(onStartMove).toHaveBeenCalledTimes(1);
  });

  it("triggers onStartResize with mode 'height' for bottom handle and 'both' for corner handle", () => {
    const panel = mockPanel("1");
    const onStartResize = vi.fn();

    render(
      <PanelFrame panel={panel} onState={vi.fn()} onStartResize={onStartResize}>
        <div>Content</div>
      </PanelFrame>
    );

    const bottomHandle = screen.getByRole("separator", { name: "Resize height of Panel 1" });
    fireEvent.pointerDown(bottomHandle, { clientX: 100, clientY: 200, pointerId: 1 });
    expect(onStartResize).toHaveBeenCalledWith("height", expect.anything());

    const cornerHandle = screen.getByRole("separator", { name: "Resize Panel 1" });
    fireEvent.pointerDown(cornerHandle, { clientX: 100, clientY: 200, pointerId: 1 });
    expect(onStartResize).toHaveBeenCalledWith("both", expect.anything());
  });

  it("does not expose resize handles when minimized or maximized", () => {
    const minPanel = mockPanel("min", { state: "minimized" });
    const { rerender } = render(
      <PanelFrame panel={minPanel} onState={vi.fn()}>
        <div>Content</div>
      </PanelFrame>
    );

    expect(screen.queryByRole("separator", { name: /resize/i })).toBeNull();

    const maxPanel = mockPanel("max", { state: "maximized" });
    rerender(
      <PanelFrame panel={maxPanel} onState={vi.fn()}>
        <div>Content</div>
      </PanelFrame>
    );

    expect(screen.queryByRole("separator", { name: /resize/i })).toBeNull();
  });

  it("invokes onBringToFront on panel click without triggering move or resize", () => {
    const panel = mockPanel("1");
    const onBringToFront = vi.fn();
    const onStartMove = vi.fn();

    render(
      <PanelFrame
        panel={panel}
        onState={vi.fn()}
        onBringToFront={onBringToFront}
        onStartMove={onStartMove}
      >
        <div data-testid="panel-body-content">Table Body</div>
      </PanelFrame>
    );

    const bodyContent = screen.getByTestId("panel-body-content");
    fireEvent.pointerDown(bodyContent);
    expect(onBringToFront).toHaveBeenCalledTimes(1);
    expect(onStartMove).not.toHaveBeenCalled();
  });
});
