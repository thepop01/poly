import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkspaceTabs from "@/components/research/WorkspaceTabs";
import type { ResearchWorkspace } from "@/types/research";

const sampleWorkspaces: ResearchWorkspace[] = [
  { workspace_id: "ws-1", name: "Cricket Research", created_at: "", updated_at: "" },
  { workspace_id: "ws-2", name: "Macro Markets", created_at: "", updated_at: "" },
];

function makeProps(overrides = {}) {
  return {
    workspaces: sampleWorkspaces,
    activeWorkspaceId: "ws-1",
    loading: false,
    onSelect: vi.fn(),
    onCreate: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
}

describe("WorkspaceTabs", () => {
  it("renders workspace tabs with active state", () => {
    render(<WorkspaceTabs {...makeProps()} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(screen.getByRole("tab", { name: /cricket research/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /macro markets/i })).toHaveAttribute("aria-selected", "false");
  });

  it("selects a workspace tab on click", async () => {
    const user = userEvent.setup();
    const p = makeProps();
    render(<WorkspaceTabs {...p} />);
    await user.click(screen.getByRole("tab", { name: /macro markets/i }));
    expect(p.onSelect).toHaveBeenCalledWith("ws-2");
  });

  it("calls onCreate when clicking New Canvas button", async () => {
    const user = userEvent.setup();
    const p = makeProps();
    render(<WorkspaceTabs {...p} />);
    await user.click(screen.getByRole("button", { name: /new research workspace/i }));
    expect(p.onCreate).toHaveBeenCalledTimes(1);
  });

  it("allows renaming inline with enter key", async () => {
    const user = userEvent.setup();
    const p = makeProps();
    render(<WorkspaceTabs {...p} />);
    await user.click(screen.getByRole("button", { name: /rename cricket research/i }));
    const input = screen.getByLabelText("Workspace name");
    await user.clear(input);
    await user.type(input, "T20 World Cup{Enter}");
    expect(p.onRename).toHaveBeenCalledWith("ws-1", "T20 World Cup");
  });
});
