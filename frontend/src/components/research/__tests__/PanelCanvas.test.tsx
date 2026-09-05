import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PanelCanvas from "@/components/research/PanelCanvas";
import type { PanelType, ResearchPanel } from "@/types/research";
import { getResultPage } from "@/utils/researchApi";

vi.mock("@/utils/researchApi", () => ({
  getResultPage: vi.fn(),
}));

const mockedGetResultPage = vi.mocked(getResultPage);

function panel(id: string, type: PanelType, overrides = {}): ResearchPanel {
  return {
    panel_id: id,
    chat_id: "chat-1",
    result_set_id: `rs-${id}`,
    panel_type: type,
    panel_key: `key-${id}`,
    title: `Title ${id}`,
    state: "normal",
    layout: { col_span: 12, min_height: 420, order: 0 },
    config: {
      result_kind: type,
      summary: {
        evidence_floor: 20,
        scope: { category: "Sports", subcategory: "Cricket", league: "T20", window_size: 0 },
      },
      row_count: 250,
      snapshot_at: "2026-09-02T10:00:00Z",
    },
    created_at: "2026-09-02T10:00:00Z",
    updated_at: "2026-09-02T10:00:00Z",
    ...overrides,
  };
}

const PAYLOADS: Record<string, Record<string, unknown>> = {
  "rs-w": {
    address: "0xabc123", username: "sharp", win_rate: 82.5, resolved_count: 40,
    winning_count: 33, pnl: 1200, volume: 9000, balance: 500, position_value: 120,
    last_trade_at: "2026-09-01T00:00:00Z",
  },
  "rs-m": {
    condition_id: "0xm1", title: "Market One", category: "Sports", subcategory: "Cricket",
    league: "T20", wallet_count: 3, open_wallets: 3, closed_wallets: 0,
    outcomes: ["YES", "NO"], total_value: 500, coverage_pct: 100,
  },
  "rs-o": {
    condition_id: "0xm1", title: "Market One", wallet_count: 3, coverage_pct: 100,
    outcomes: { YES: 2, NO: 1 }, current_value: 500, input_wallet_count: 3,
  },
  "rs-c": {
    condition_id: "0xm1", title: "Market One", outcome: "YES",
    wallet_count: 2, wallet_pct: 66.67, current_value: 400,
  },
};

beforeEach(() => {
  mockedGetResultPage.mockImplementation(async (id: string, offset = 0) => ({
    summary: {
      result_set_id: id, chat_id: "chat-1", run_id: null, kind: "wallet_set",
      label: "L", definition: {}, summary: {}, row_count: 250,
      snapshot_at: "2026-09-02T10:00:00Z", created_at: "2026-09-02T10:00:00Z",
    },
    members: [0, 1].map((i) => ({
      ordinal: offset + i, entity_type: "wallet", entity_key: `${id}-${offset + i}`,
      payload: PAYLOADS[id] ?? {},
    })),
  }));
});

describe("PanelCanvas", () => {
  it("maps every panel type through the exhaustive renderer", async () => {
    const onState = vi.fn();
    render(
      <PanelCanvas
        panels={[
          panel("w", "wallet_table"),
          panel("m", "market_table"),
          panel("o", "overlap_table"),
          panel("c", "consensus"),
        ]}
        onPanelState={onState}
      />,
    );
    expect(await screen.findByText("Win rate")).toBeInTheDocument();
    expect(await screen.findByText("Total value")).toBeInTheDocument();
    expect(await screen.findAllByText("YES: 2 · NO: 1")).toHaveLength(2);
    const consensus = await screen.findByTestId("panel-c");
    expect(within(consensus).getAllByText("YES")).toHaveLength(2);
  });

  it("does not duplicate a panel when the same key upserts", async () => {
    const onState = vi.fn();
    const first = panel("w", "wallet_table");
    const { rerender } = render(<PanelCanvas panels={[first]} onPanelState={onState} />);
    expect(await screen.findByTestId("panel-w")).toBeInTheDocument();
    rerender(
      <PanelCanvas
        panels={[{ ...first, title: "Title w v2" }]}
        onPanelState={onState}
      />,
    );
    const frames = screen.getAllByTestId("panel-w");
    expect(frames).toHaveLength(1);
    expect(within(frames[0]).getByText("Title w v2")).toBeInTheDocument();
  });

  it("hides closed panels but keeps them restorable", async () => {
    const onState = vi.fn();
    const user = userEvent.setup();
    render(
      <PanelCanvas
        panels={[panel("w", "wallet_table"), panel("m", "market_table", { state: "closed" })]}
        onPanelState={onState}
      />,
    );
    expect(await screen.findByTestId("panel-w")).toBeInTheDocument();
    expect(screen.queryByTestId("panel-m")).toBeNull();
    await user.click(screen.getByRole("button", { name: /restore title m/i }));
    expect(onState).toHaveBeenCalledWith("m", "normal");
  });

  it("maximizing one panel hides the other panel bodies", async () => {
    const onState = vi.fn();
    render(
      <PanelCanvas
        panels={[panel("w", "wallet_table", { state: "maximized" }), panel("m", "market_table")]}
        onPanelState={onState}
      />,
    );
    expect(await screen.findByTestId("panel-w")).toBeInTheDocument();
    expect(screen.queryByTestId("panel-m")).toBeNull();
  });

  it("pages table panels through the server in 100-row pages", async () => {
    const onState = vi.fn();
    const user = userEvent.setup();
    render(<PanelCanvas panels={[panel("w", "wallet_table")]} onPanelState={onState} />);
    expect(await screen.findByText(/page 1 of 3/i)).toBeInTheDocument();
    expect(mockedGetResultPage).toHaveBeenCalledWith("rs-w", 0, 100);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(mockedGetResultPage).toHaveBeenCalledWith("rs-w", 100, 100);
  });

  it("displays snapshot time, row count, scope, and evidence floor", async () => {
    const onState = vi.fn();
    render(<PanelCanvas panels={[panel("w", "wallet_table")]} onPanelState={onState} />);
    const frame = await screen.findByTestId("panel-w");
    expect(within(frame).getByText(/snapshot/i)).toBeInTheDocument();
    expect(within(frame).getByText(/250 rows/)).toBeInTheDocument();
    expect(within(frame).getByText(/sports → cricket → t20/i)).toBeInTheDocument();
    expect(within(frame).getByText(/floor n≥20/)).toBeInTheDocument();
  });

  it("suggests nearby scopes when a wallet search is empty", async () => {
    const onState = vi.fn();
    mockedGetResultPage.mockResolvedValueOnce({
      summary: {
        result_set_id: "rs-empty", chat_id: "chat-1", run_id: null, kind: "wallet_set",
        label: "0 wallets", definition: {}, summary: {}, row_count: 0,
        snapshot_at: "2026-09-02T10:00:00Z", created_at: "2026-09-02T10:00:00Z",
      },
      members: [],
    });
    const empty = panel("e", "wallet_table", {
      result_set_id: "rs-empty",
      config: {
        result_kind: "wallet_set",
        summary: {
          evidence_floor: 20,
          available_scopes: [
            { subcategory: "Cricket", league: "", wallets: 11995 },
            { subcategory: "Cricket", league: "IPL", wallets: 1803 },
          ],
        },
        row_count: 0,
        snapshot_at: "2026-09-02T10:00:00Z",
      },
    });
    render(<PanelCanvas panels={[empty]} onPanelState={onState} />);
    expect(await screen.findByText(/nearby scopes/i)).toBeInTheDocument();
    expect(screen.getByText(/cricket.*11,995 wallets/i)).toBeInTheDocument();
  });

  it("brings clicked table to the upper layer (highest z-index) when multiple tables exist", async () => {
    const onState = vi.fn();
    const user = userEvent.setup();
    render(
      <PanelCanvas
        panels={[
          panel("w", "wallet_table"),
          panel("m", "market_table"),
        ]}
        onPanelState={onState}
      />,
    );
    const panelW = await screen.findByTestId("panel-w");
    const panelM = await screen.findByTestId("panel-m");
    const containerW = panelW.parentElement!;
    const containerM = panelM.parentElement!;

    // Click panel-m -> it should have higher z-index and active class
    await user.click(panelM);
    const zM1 = Number(containerM.style.zIndex);
    const zW1 = Number(containerW.style.zIndex);
    expect(zM1).toBeGreaterThan(zW1);
    expect(panelM).toHaveClass("research-panel-active");

    // Click panel-w -> panel-w must now overlap panel-m in upper layer
    await user.click(panelW);
    const zM2 = Number(containerM.style.zIndex);
    const zW2 = Number(containerW.style.zIndex);
    expect(zW2).toBeGreaterThan(zM2);
    expect(panelW).toHaveClass("research-panel-active");
  });
});
