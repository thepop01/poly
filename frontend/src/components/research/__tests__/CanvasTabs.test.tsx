import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CanvasTabs from "@/components/research/CanvasTabs";

describe("CanvasTabs", () => {
  it("renders only fixed tabs, selection, and keyboard activation", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<CanvasTabs tabs={[{ workspace_tab_id: "x", workspace_id: "w", tab_type: "agents", label: "Injected", created_at: "" }]} activeTabType="wallet_groups" onSelect={onSelect} />);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Wallet Groups", "Market Groups", "Agents"]);
    expect(screen.getByRole("tab", { name: "Wallet Groups" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Agents" }));
    expect(onSelect).toHaveBeenCalledWith("agents");
    screen.getByRole("tab", { name: "Market Groups" }).focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(onSelect).toHaveBeenCalledWith("market_groups");
  });

  it("keeps all fixed tabs present while loading", () => {
    render(<CanvasTabs tabs={undefined} activeTabType="agents" onSelect={vi.fn()} />);
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByText(/loading canvas tabs/i)).toBeInTheDocument();
  });
});
