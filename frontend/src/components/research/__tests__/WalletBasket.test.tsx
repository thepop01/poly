import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import WalletTablePanel from "../panels/WalletTablePanel";
import type { ResearchPanel } from "@/types/research";

vi.mock("@/utils/api", () => ({
  getWalletStats: vi.fn().mockImplementation(async (address: string) => {
    if (address.includes("3333")) {
      return {
        address,
        username: "whale3",
        win_rate: 76.5,
        resolved_count: 50,
        winning_count: 38,
        total_pnl: 15000,
        total_volume: 85000,
        balance: 500,
        position_value: 250,
        last_trade_at: "2026-09-03T00:00:00Z",
      };
    }
    return {
      address,
      username: "traderX",
      win_rate: 80.0,
      resolved_count: 10,
      winning_count: 8,
      total_pnl: 3000,
      total_volume: 12000,
      balance: 100,
      position_value: 50,
      last_trade_at: "2026-09-03T00:00:00Z",
    };
  }),
}));

vi.mock("@/utils/researchApi", () => ({
  getResultPage: vi.fn().mockResolvedValue({
    summary: { row_count: 2 },
    members: [
      {
        ordinal: 1,
        entity_type: "wallet",
        entity_key: "0xbase111111111111111111111111111111111111",
        payload: {
          address: "0xbase111111111111111111111111111111111111",
          username: "whale1",
          win_rate: 75.0,
          resolved_count: 20,
          winning_count: 15,
          pnl: 5000,
          volume: 25000,
          balance: 1000,
          position_value: 200,
          last_trade_at: "2026-09-01T00:00:00Z",
        },
      },
      {
        ordinal: 2,
        entity_type: "wallet",
        entity_key: "0xbase222222222222222222222222222222222222",
        payload: {
          address: "0xbase222222222222222222222222222222222222",
          username: "whale2",
          win_rate: 60.0,
          resolved_count: 10,
          winning_count: 6,
          pnl: 1200,
          volume: 8000,
          balance: 300,
          position_value: 50,
          last_trade_at: "2026-09-02T00:00:00Z",
        },
      },
    ],
  }),
}));

function mockPanel(id = "w1", overrides: Partial<ResearchPanel> = {}): ResearchPanel {
  return {
    panel_id: id,
    workspace_id: "workspace-1",
    source_chat_id: "chat-1",
    result_set_id: "rs-w1",
    panel_type: "wallet_table",
    panel_key: `key-${id}`,
    title: "Alpha Wallets Basket",
    state: "normal",
    layout: { col_span: 6, min_height: 380, order: 0 },
    config: { row_count: 2 },
    created_at: "2026-09-02T10:00:00Z",
    updated_at: "2026-09-02T10:00:00Z",
    ...overrides,
  };
}

describe("WalletTablePanel Basket Functionality", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders basket toolbar with wallet count badge", async () => {
    const panel = mockPanel();
    render(<WalletTablePanel panel={panel} />);

    expect(await screen.findByText("Wallet Basket")).toBeInTheDocument();
    expect(screen.getByTestId("basket-count")).toHaveTextContent("2 wallets");
    expect(screen.getByText("whale1")).toBeInTheDocument();
    expect(screen.getByText("whale2")).toBeInTheDocument();
  });

  it("manually adds a wallet and automatically hydrates live data (win rate, PnL, volume)", async () => {
    const panel = mockPanel();
    const onSaveMutation = vi.fn().mockResolvedValue(null);

    render(<WalletTablePanel panel={panel} onSaveMutation={onSaveMutation} />);

    expect(await screen.findByText("whale1")).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/add wallet address/i);
    const addBtn = screen.getByRole("button", { name: /add wallet to table/i });

    fireEvent.change(input, { target: { value: "0x3333333333333333333333333333333333333333" } });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByTestId("basket-count")).toHaveTextContent("3 wallets");
    });

    expect(screen.getByText("whale3")).toBeInTheDocument();
    expect(screen.getByText("76.5%")).toBeInTheDocument();
    expect(screen.getByText("$15,000")).toBeInTheDocument();
    expect(screen.getByText("$85,000")).toBeInTheDocument();
    expect(screen.getByText(/38-12/)).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();

    expect(onSaveMutation).toHaveBeenCalledWith(
      "w1",
      expect.objectContaining({
        config: expect.objectContaining({
          custom_wallets: expect.arrayContaining([
            expect.objectContaining({
              entity_key: "0x3333333333333333333333333333333333333333",
            }),
          ]),
        }),
      })
    );
  });

  it("supports batch adding multiple comma-separated wallets", async () => {
    const panel = mockPanel();
    const onSaveMutation = vi.fn().mockResolvedValue(null);

    render(<WalletTablePanel panel={panel} onSaveMutation={onSaveMutation} />);

    expect(await screen.findByText("whale1")).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/add wallet address/i);
    const addBtn = screen.getByRole("button", { name: /add wallet to table/i });

    fireEvent.change(input, {
      target: { value: "0x4444444444444444444444444444444444444444, 0x5555555555555555555555555555555555555555" },
    });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByTestId("basket-count")).toHaveTextContent("4 wallets");
    });
    expect(onSaveMutation).toHaveBeenCalled();
  });

  it("automatically background-hydrates existing custom wallets with missing data", async () => {
    const panelWithUnfinishedWallet = mockPanel("w-custom", {
      config: {
        row_count: 2,
        custom_wallets: [
          {
            ordinal: 99,
            entity_type: "wallet",
            entity_key: "0x3333333333333333333333333333333333333333",
            payload: {
              address: "0x3333333333333333333333333333333333333333",
              win_rate: null,
              pnl: null,
              volume: null,
              is_custom: true,
            },
          },
        ],
      },
    });

    render(<WalletTablePanel panel={panelWithUnfinishedWallet} />);

    // After background hydration, whale3 stats should appear automatically
    expect(await screen.findByText("whale3")).toBeInTheDocument();
    expect(await screen.findByText("76.5%")).toBeInTheDocument();
    expect(screen.getByText("$15,000")).toBeInTheDocument();
  });

  it("deletes a wallet from the basket and updates the count", async () => {
    const panel = mockPanel();
    const onSaveMutation = vi.fn().mockResolvedValue(null);

    render(<WalletTablePanel panel={panel} onSaveMutation={onSaveMutation} />);

    expect(await screen.findByText("whale1")).toBeInTheDocument();

    const deleteBtn = screen.getByRole("button", {
      name: "Remove wallet 0xbase111111111111111111111111111111111111",
    });
    fireEvent.click(deleteBtn);

    expect(screen.queryByText("whale1")).toBeNull();
    expect(screen.getByTestId("basket-count")).toHaveTextContent("1 wallets");

    expect(onSaveMutation).toHaveBeenCalledWith(
      "w1",
      expect.objectContaining({
        config: expect.objectContaining({
          removed_wallet_keys: expect.arrayContaining([
            "0xbase111111111111111111111111111111111111",
          ]),
        }),
      })
    );
  });
});
