"use client";

import { useState } from "react";
import type { ResultMember } from "@/types/research";
import { ChevronDown, ChevronUp, Layers } from "lucide-react";

interface PositionsBarProps {
  /** Position data rows from research results */
  rows: ResultMember[];
  /** Active chat title for tab label */
  chatTitle?: string;
}

type BarTab = "positions" | "orders" | "fills" | "taker";

const BAR_TABS: { key: BarTab; label: string }[] = [
  { key: "positions", label: "Positions" },
  { key: "orders", label: "Orders" },
  { key: "fills", label: "Fills history" },
  { key: "taker", label: "Taker Activity" },
];

const COL_HEADERS = ["Markets", "Ticker", "Side", "Contracts", "Avg", "Cost", "Payout if right", "Market value", "Day P&L", "Total"];

function extractPositionCols(row: ResultMember) {
  const d = (row.payload ?? {}) as Record<string, unknown>;
  return {
    market: String(d.market_slug ?? d.market ?? "—"),
    ticker: String(d.ticker ?? "—"),
    side: String(d.outcome ?? d.side ?? "—"),
    contracts: Number(d.size ?? d.contracts ?? 0),
    avg: Number(d.avg_price ?? d.avg ?? 0),
    cost: Number(d.cost ?? 0),
    payout: Number(d.payout ?? 0),
    value: Number(d.market_value ?? 0),
    dayPnl: Number(d.day_pnl ?? 0),
    total: Number(d.total_pnl ?? 0),
  };
}

export default function PositionsBar({ rows, chatTitle }: PositionsBarProps) {
  const [open, setOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<BarTab>("positions");

  const posRows = rows.slice(0, 50);

  return (
    <div className={`positions-bar ${open ? "positions-bar-open" : "positions-bar-closed"}`}>
      {/* Bar header strip */}
      <div className="positions-bar-header">
        {/* Chat ticker chip */}
        {chatTitle && (
          <div className="positions-chat-chip">
            <Layers size={10} className="text-subtle" />
            <span className="truncate max-w-32">{chatTitle}</span>
            <span className="text-subtle/60">×</span>
          </div>
        )}

        {/* Sub-tabs */}
        <div className="positions-tabs">
          {BAR_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`positions-tab-btn ${activeTab === tab.key ? "active" : ""}`}
            >
              {tab.label}
              {tab.key === "orders" && posRows.length > 0 && (
                <span className="positions-tab-count">{Math.min(posRows.length, 9)}</span>
              )}
            </button>
          ))}
        </div>

        {/* Sort icon placeholder */}
        <button type="button" className="ml-auto text-subtle hover:text-foreground transition-colors p-1 rounded" title="Sort columns">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M7 12h10M11 18h2" />
          </svg>
        </button>

        {/* Collapse toggle */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="positions-collapse-btn"
          title={open ? "Collapse positions" : "Expand positions"}
          aria-label={open ? "Collapse positions bar" : "Expand positions bar"}
        >
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>
      </div>

      {/* Table body */}
      {open && (
        <div className="positions-bar-body">
          {activeTab !== "positions" ? (
            <div className="flex items-center justify-center h-20 text-sm text-subtle">
              No {activeTab} data available
            </div>
          ) : posRows.length === 0 ? (
            <div className="flex items-center justify-center h-20 text-sm text-subtle">
              Run a wallet or market analysis to populate positions.
            </div>
          ) : (
            <table className="positions-table">
              <thead>
                <tr>
                  {COL_HEADERS.map((col) => (
                    <th key={col} className="positions-th">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {posRows.map((row, i) => {
                  const p = extractPositionCols(row);
                  const pnlPositive = p.total >= 0;
                  return (
                    <tr key={i} className="positions-tr">
                      <td className="positions-td font-medium truncate max-w-[140px]">{p.market}</td>
                      <td className="positions-td font-mono text-xs">{p.ticker}</td>
                      <td className={`positions-td font-semibold text-xs ${p.side.toLowerCase() === "yes" ? "text-success" : "text-danger"}`}>
                        {p.side}
                      </td>
                      <td className="positions-td font-mono text-xs text-right">{p.contracts.toLocaleString()}</td>
                      <td className="positions-td font-mono text-xs text-right">{p.avg > 0 ? `${(p.avg * 100).toFixed(0)}¢` : "—"}</td>
                      <td className="positions-td font-mono text-xs text-right">{p.cost > 0 ? `$${p.cost.toFixed(2)}` : "—"}</td>
                      <td className="positions-td font-mono text-xs text-right">{p.payout > 0 ? `$${p.payout.toFixed(2)}` : "—"}</td>
                      <td className="positions-td font-mono text-xs text-right">{p.value > 0 ? `$${p.value.toFixed(2)}` : "—"}</td>
                      <td className={`positions-td font-mono text-xs text-right ${p.dayPnl >= 0 ? "text-success" : "text-danger"}`}>
                        {p.dayPnl !== 0 ? `${p.dayPnl >= 0 ? "+" : ""}$${p.dayPnl.toFixed(2)}` : "—"}
                      </td>
                      <td className={`positions-td font-mono text-xs text-right font-semibold ${pnlPositive ? "text-success" : "text-danger"}`}>
                        {p.total !== 0 ? `${pnlPositive ? "+" : ""}$${p.total.toFixed(2)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
