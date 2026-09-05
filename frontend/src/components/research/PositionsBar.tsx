"use client";

import { useState } from "react";
import type { ResearchPosition } from "@/types/research";
import { ArrowUp, ChevronDown, ChevronUp, Layers } from "lucide-react";

interface PositionsBarProps {
  rows: ResearchPosition[];
  chatTitle?: string;
  selectedPosition?: ResearchPosition | null;
  onSelectPosition?: (position: ResearchPosition) => void;
  isOpen?: boolean;
  onToggleOpen?: () => void;
}

type BarTab = "positions" | "orders" | "fills" | "taker";

const BAR_TABS: { key: BarTab; label: string }[] = [
  { key: "positions", label: "Positions" },
  { key: "orders", label: "Orders" },
  { key: "fills", label: "Fills history" },
  { key: "taker", label: "Taker Activity" },
];

const COL_HEADERS = [
  "Market",
  "Side",
  "Contracts",
  "Avg Price",
  "Current Value",
  "Unrealized P&L",
];

function formatCurrency(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
}

function formatNumber(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return val.toLocaleString();
}

export default function PositionsBar({
  rows,
  chatTitle,
  selectedPosition,
  onSelectPosition,
  isOpen: controlledOpen,
  onToggleOpen,
}: PositionsBarProps) {
  const [internalOpen, setInternalOpen] = useState(true);
  const open = controlledOpen !== undefined ? controlledOpen : internalOpen;
  const toggleOpen = onToggleOpen ?? (() => setInternalOpen((o) => !o));
  const [activeTab, setActiveTab] = useState<BarTab>("positions");

  const isSelected = (pos: ResearchPosition) =>
    Boolean(
      selectedPosition &&
      selectedPosition.condition_id === pos.condition_id &&
      selectedPosition.address === pos.address &&
      selectedPosition.outcome === pos.outcome
    );

  return (
    <div className={`positions-bar ${open ? "positions-bar-open" : "positions-bar-closed"}`}>
      {/* Bar header strip */}
      <div className="positions-bar-header">
        {chatTitle && (
          <div className="positions-chat-chip">
            <Layers size={10} className="text-subtle" />
            <span className="truncate max-w-32">{chatTitle}</span>
          </div>
        )}

        {/* Sub-tabs */}
        <div className="positions-tabs" role="tablist">
          {BAR_TABS.map((tab) => {
            const count = tab.key === "positions" ? rows.length : undefined;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`positions-tab-btn ${activeTab === tab.key ? "active" : ""}`}
              >
                {tab.label}
                {count !== undefined && count > 0 && (
                  <span className="positions-tab-count">{count}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Scroll back to canvas button */}
        <button
          type="button"
          onClick={() => {
            if (typeof document !== "undefined") {
              const workspace = document.querySelector(".research-workspace");
              if (workspace && typeof workspace.scrollTo === "function") {
                workspace.scrollTo({ top: 0, behavior: "smooth" });
              }
            }
          }}
          className="positions-jump-btn ml-auto"
          title="Scroll up to Canvas & Terminal"
          aria-label="Scroll to Canvas"
        >
          <ArrowUp size={11} />
          <span>Canvas</span>
        </button>

        {/* Collapse toggle */}
        <button
          type="button"
          onClick={toggleOpen}
          className="positions-collapse-btn"
          aria-label={open ? "Collapse positions bar" : "Expand positions bar"}
          title={open ? "Collapse positions" : "Expand positions"}
        >
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      {/* Bar body */}
      {open && (
        <div className="positions-bar-body overflow-x-auto">
          {activeTab === "positions" && (
            rows.length === 0 ? (
              <div className="flex items-center justify-center h-24 text-subtle text-xs">
                No open positions for wallets in this chat.
              </div>
            ) : (
              <table className="positions-table">
                <thead>
                  <tr>
                    {COL_HEADERS.map((h) => (
                      <th key={h} className="positions-th">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, idx) => {
                    const marketLabel = row.market_title ?? row.condition_id;
                    const selected = isSelected(row);
                    const pnlPositive = (row.unrealized_pnl ?? 0) >= 0;
                    return (
                      <tr
                        key={`${row.address}-${row.condition_id}-${row.outcome ?? idx}`}
                        className={`positions-tr ${selected ? "positions-tr-selected bg-primary/5" : "hover:bg-surface-2/50"}`}
                      >
                        <td className="positions-td font-medium max-w-[200px] truncate">
                          <button
                            type="button"
                            onClick={() => onSelectPosition?.(row)}
                            className="text-left font-medium text-foreground hover:text-primary transition-colors truncate block w-full focus:outline-none"
                            title={marketLabel}
                          >
                            {marketLabel}
                          </button>
                        </td>
                        <td className="positions-td font-semibold text-xs">
                          {row.outcome ? (
                            <span
                              className={
                                row.outcome.toUpperCase() === "YES"
                                  ? "text-success"
                                  : row.outcome.toUpperCase() === "NO"
                                  ? "text-danger"
                                  : "text-foreground"
                              }
                            >
                              {row.outcome}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="positions-td font-mono text-xs text-right">
                          {formatNumber(row.size)}
                        </td>
                        <td className="positions-td font-mono text-xs text-right">
                          {formatCurrency(row.avg_price)}
                        </td>
                        <td className="positions-td font-mono text-xs text-right font-medium">
                          {formatCurrency(row.current_value)}
                        </td>
                        <td
                          className={`positions-td font-mono text-xs text-right ${
                            row.unrealized_pnl !== null && row.unrealized_pnl !== undefined
                              ? pnlPositive
                                ? "text-success"
                                : "text-danger"
                              : ""
                          }`}
                        >
                          {row.unrealized_pnl !== null && row.unrealized_pnl !== undefined
                            ? `${pnlPositive ? "+" : ""}${formatCurrency(row.unrealized_pnl)}`
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )
          )}

          {activeTab === "orders" && (
            <div className="flex items-center justify-center h-24 text-subtle text-xs">
              Orders unavailable in research preview.
            </div>
          )}

          {activeTab === "fills" && (
            <div className="flex items-center justify-center h-24 text-subtle text-xs">
              Fills history unavailable in research preview.
            </div>
          )}

          {activeTab === "taker" && (
            <div className="flex items-center justify-center h-24 text-subtle text-xs">
              Taker activity unavailable in research preview.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
