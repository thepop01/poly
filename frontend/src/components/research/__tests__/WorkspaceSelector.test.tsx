import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkspaceSelector from "@/components/research/WorkspaceSelector";
import type { ResearchWorkspace } from "@/types/research";

const workspaces: ResearchWorkspace[] = [
  { workspace_id: "one", name: "First", created_at: "", updated_at: "" },
  { workspace_id: "two", name: "Second", created_at: "", updated_at: "" },
];
const props = () => ({ workspaces, activeWorkspaceId: "one", onSelect: vi.fn(), onCreate: vi.fn(), onRename: vi.fn(), onDelete: vi.fn() });

describe("WorkspaceSelector", () => {
  it("selects, creates, renames, and requests deletion accessibly", async () => {
    const user = userEvent.setup();
    const p = props();
    render(<WorkspaceSelector {...p} />);
    await user.selectOptions(screen.getByRole("combobox"), "two");
    expect(p.onSelect).toHaveBeenCalledWith("two");
    await user.click(screen.getByRole("button", { name: /create workspace/i }));
    expect(p.onCreate).toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /rename first/i }));
    await user.clear(screen.getByRole("textbox", { name: "Workspace name" }));
    await user.type(screen.getByRole("textbox", { name: "Workspace name" }), "Renamed");
    await user.click(screen.getByRole("button", { name: /save workspace name/i }));
    expect(p.onRename).toHaveBeenCalledWith("one", "Renamed");
    await user.click(screen.getByRole("button", { name: /delete first/i }));
    expect(p.onDelete).toHaveBeenCalledWith("one");
  });
});
