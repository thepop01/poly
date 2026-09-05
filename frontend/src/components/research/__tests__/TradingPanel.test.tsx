import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import TradingPanel from "../TradingPanel";
import type { ResearchPosition } from "@/types/research";

const mockPosition: ResearchPosition = {
  address: "0x1234567890abcdef1234567890abcdef12345678",
  condition_id: "0xcondition_xyz",
  market_title: "Will CPI exceed 3.5%?",
  outcome: "YES",
  size: 50,
  avg_price: 0.6,
  current_value: 30.0,
  unrealized_pnl: 5.0,
  entry_at: null,
  computed_at: null,
};

describe("TradingPanel (Mock Order Ticket)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("visibly states that it is a mock preview only", () => {
    render(<TradingPanel />);
    expect(screen.getAllByText(/preview only|mock order ticket/i).length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/order placement is not integrated|trading is simulated/i),
    ).toBeInTheDocument();
  });

  it("displays selected market title and outcome when position is provided", () => {
    render(<TradingPanel selectedPosition={mockPosition} />);
    expect(screen.getByText("Will CPI exceed 3.5%?")).toBeInTheDocument();
    expect(screen.getAllByText("YES").length).toBeGreaterThanOrEqual(1);
  });

  it("displays empty market prompt when no position is selected", () => {
    render(<TradingPanel />);
    expect(screen.getByText(/select a position to preview/i)).toBeInTheDocument();
  });

  it("has a 'Review mock order' button that never calls fetch or submits an order", async () => {
    const user = userEvent.setup();
    render(<TradingPanel selectedPosition={mockPosition} />);

    const reviewBtn = screen.getByRole("button", { name: /review mock order/i });
    expect(reviewBtn).toBeInTheDocument();

    await user.click(reviewBtn);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("renders collapsed toggle when visible is false", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<TradingPanel visible={false} onToggle={onToggle} />);

    const toggleBtn = screen.getByRole("button", { name: /show mock trading ticket|expand trading panel/i });
    expect(toggleBtn).toBeInTheDocument();

    await user.click(toggleBtn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
