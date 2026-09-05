import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PositionsBar from "../PositionsBar";
import type { ResearchPosition } from "@/types/research";

const mockPosition: ResearchPosition = {
  address: "0x1234567890abcdef1234567890abcdef12345678",
  condition_id: "0xcondition123",
  market_title: "Market Alpha",
  outcome: "YES",
  size: 25,
  avg_price: 0.5,
  current_value: 12.5,
  unrealized_pnl: 2.5,
  entry_at: null,
  computed_at: null,
};

describe("PositionsBar", () => {
  it("renders real position row and handles selection", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<PositionsBar rows={[mockPosition]} onSelectPosition={onSelect} />);

    expect(screen.getByText("Market Alpha")).toBeInTheDocument();
    expect(screen.getByText("YES")).toBeInTheDocument();
    expect(screen.getByText("$12.50")).toBeInTheDocument();

    const selectBtn = screen.getByRole("button", { name: /market alpha/i });
    await user.click(selectBtn);
    expect(onSelect).toHaveBeenCalledWith(mockPosition);
  });

  it("renders empty state when rows are empty", () => {
    render(<PositionsBar rows={[]} />);
    expect(screen.getByText(/no open positions/i)).toBeInTheDocument();
  });

  it("renders null values as em dash —", () => {
    const nullPos: ResearchPosition = {
      address: "0x999",
      condition_id: "0xcond_fallback",
      market_title: null,
      outcome: null,
      size: null,
      avg_price: null,
      current_value: null,
      unrealized_pnl: null,
      entry_at: null,
      computed_at: null,
    };
    render(<PositionsBar rows={[nullPos]} />);
    expect(screen.getByText("0xcond_fallback")).toBeInTheDocument();
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it("has accessible collapse and expand control", async () => {
    const user = userEvent.setup();
    render(<PositionsBar rows={[mockPosition]} />);
    const collapseBtn = screen.getByRole("button", { name: /collapse positions bar/i });
    expect(collapseBtn).toBeInTheDocument();
    await user.click(collapseBtn);
    expect(screen.getByRole("button", { name: /expand positions bar/i })).toBeInTheDocument();
  });

  it("shows unavailable empty states for non-positions tabs", async () => {
    const user = userEvent.setup();
    render(<PositionsBar rows={[mockPosition]} />);
    await user.click(screen.getByRole("tab", { name: /orders/i }));
    expect(screen.getByText(/orders unavailable/i)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /fills/i }));
    expect(screen.getByText(/fills history unavailable/i)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /taker/i }));
    expect(screen.getByText(/taker activity unavailable/i)).toBeInTheDocument();
  });
});
