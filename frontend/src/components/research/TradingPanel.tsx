"use client";

import { useState } from "react";
import type { ResultMember } from "@/types/research";
import { TrendingUp, TrendingDown, Info } from "lucide-react";

interface TradingPanelProps {
  /** Latest position rows from research results to display in position view */
  positionRows?: ResultMember[];
  /** Whether this panel is visible */
  visible?: boolean;
  /** Toggle visibility */
  onToggle?: () => void;
}

type TradeSide = "yes" | "no";
type OrderType = "limit" | "market";

const SHARE_PRESETS = [100, 500, 1000];

export default function TradingPanel({
  positionRows = [],
  visible = true,
  onToggle,
}: TradingPanelProps) {
  const [side, setSide] = useState<TradeSide>("yes");
  const [shares, setShares] = useState(100);
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [limitPrice, setLimitPrice] = useState<string>("AUTO");

  // Derived display values (display-only placeholders)
  const yesPriceCents = 63;
  const noPriceCents = 36;
  const currentPrice = side === "yes" ? yesPriceCents : noPriceCents;
  const cost = ((currentPrice / 100) * shares).toFixed(2);
  const maxPayout = shares.toFixed(2);
  const strike = "Above 3.3%";

  if (!visible) {
    return (
      <aside className="trading-panel-hidden" aria-label="Trading panel collapsed">
        <button
          type="button"
          onClick={onToggle}
          className="trading-panel-toggle-btn"
          title="Show position panel"
        >
          <TrendingUp size={14} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="trading-panel" aria-label="Position view panel">
      {/* Panel header */}
      <div className="trading-panel-header">
        <span className="text-xs font-semibold text-foreground">Position View</span>
        <button
          type="button"
          onClick={onToggle}
          className="trading-panel-close-btn"
          title="Collapse panel"
          aria-label="Collapse position panel"
        >
          <TrendingDown size={12} />
        </button>
      </div>

      {/* Buy / Sell toggle */}
      <div className="trading-side-toggle">
        <button
          type="button"
          className={`trading-side-btn ${side === "yes" ? "trading-side-btn-yes active" : ""}`}
          onClick={() => setSide("yes")}
        >
          Buy
        </button>
        <button
          type="button"
          className={`trading-side-btn ${side === "no" ? "trading-side-btn-no active" : ""}`}
          onClick={() => setSide("no")}
        >
          Sell
        </button>
        <span className="trading-side-label">Limit</span>
      </div>

      {/* Strike name */}
      <div className="trading-strike">
        <p className="text-xs font-semibold text-foreground truncate">{strike}</p>
      </div>

      {/* Yes / No price pills */}
      <div className="trading-price-row">
        <button
          type="button"
          onClick={() => setSide("yes")}
          className={`trading-price-pill trading-price-pill-yes ${side === "yes" ? "active" : ""}`}
          title="Buy YES"
        >
          Yes {yesPriceCents}¢
        </button>
        <button
          type="button"
          onClick={() => setSide("no")}
          className={`trading-price-pill trading-price-pill-no ${side === "no" ? "active" : ""}`}
          title="Buy NO"
        >
          No {noPriceCents}¢
        </button>
      </div>

      {/* Account balance display */}
      <div className="trading-row-label">
        <span className="text-xs text-subtle">Predictions account</span>
        <span className="text-xs font-mono text-foreground">$132.97 avail</span>
      </div>

      {/* Shares row */}
      <div className="trading-field-group">
        <label className="trading-field-label">Shares</label>
        <div className="trading-shares-presets">
          {SHARE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => setShares(preset)}
              className={`trading-preset-btn ${shares === preset ? "active" : ""}`}
            >
              {preset.toLocaleString()}
            </button>
          ))}
        </div>
        <input
          type="number"
          value={shares}
          min={1}
          onChange={(e) => setShares(Math.max(1, Number(e.target.value)))}
          className="trading-input"
          aria-label="Number of shares"
        />
      </div>

      {/* Limit price row */}
      <div className="trading-row-label">
        <label className="trading-field-label">Limit price</label>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setOrderType(orderType === "limit" ? "market" : "limit")}
            className={`trading-preset-btn text-xs ${orderType === "limit" ? "active" : ""}`}
          >
            AUTO
          </button>
          <span className="text-subtle text-xs">—</span>
          <span className="text-xs font-mono text-foreground">{currentPrice}¢</span>
        </div>
      </div>

      {/* Expiration row */}
      <div className="trading-row-label">
        <label className="trading-field-label">Expiration</label>
        <span className="text-xs text-foreground font-mono">8/12/2026, 8:00 AM EDT</span>
      </div>

      {/* At event start chip */}
      <div className="px-3 py-1">
        <span className="trading-event-chip">At the event start</span>
      </div>

      {/* Time-in-force row */}
      <div className="trading-tif-row">
        {["GTC", "EOD", "IOC", "Custom"].map((tif) => (
          <button key={tif} type="button" className={`trading-tif-btn ${tif === "GTC" ? "active" : ""}`}>
            {tif}
          </button>
        ))}
      </div>

      {/* Post only toggle */}
      <div className="trading-row-label px-3 py-1">
        <span className="text-xs text-subtle">Post only</span>
        <div className="w-8 h-4 rounded-full bg-surface-3 border border-border relative cursor-pointer">
          <div className="absolute left-0.5 top-0.5 w-3 h-3 rounded-full bg-subtle transition-transform" />
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-border mx-3 my-1" />

      {/* Cost / Payout summary */}
      <div className="trading-summary">
        <div className="trading-row-label">
          <span className="text-xs text-subtle flex items-center gap-1">
            Cost <Info size={10} className="text-subtle" />
          </span>
          <span className="text-xs font-mono text-foreground">${cost}</span>
        </div>
        <div className="trading-row-label">
          <span className="text-xs text-subtle flex items-center gap-1">
            Max payout
          </span>
          <span className="text-xs font-mono text-foreground">${maxPayout}</span>
        </div>
        {positionRows.length === 0 && (
          <div className="trading-row-label">
            <span className="text-xs text-subtle">Earn interest</span>
            <span className="text-xs font-mono text-foreground">$3.2—</span>
          </div>
        )}
      </div>

      {/* Research positions list (display-only) */}
      {positionRows.length > 0 && (
        <div className="trading-positions-list">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-subtle px-3 pt-2 pb-1">
            Wallet Positions
          </p>
          <div className="overflow-y-auto max-h-40">
            {positionRows.slice(0, 8).map((row, i) => {
              const payload = (row.payload ?? {}) as Record<string, unknown>;
              const market = String(payload.market_slug ?? "—");
              const side = String(payload.outcome ?? "—");
              const size = Number(payload.size ?? 0);
              return (
                <div key={i} className="trading-position-row">
                  <span className="truncate text-[11px] text-foreground max-w-[100px]">{market}</span>
                  <span className={`text-[11px] font-semibold ${side.toLowerCase() === "yes" ? "text-success" : "text-danger"}`}>
                    {side}
                  </span>
                  <span className="text-[11px] font-mono text-foreground">{size.toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* CTA button */}
      <div className="p-3 pt-2">
        <button
          type="button"
          className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-all duration-150 cursor-pointer ${
            side === "yes"
              ? "bg-success hover:bg-success/90 shadow-sm shadow-success/30"
              : "bg-danger hover:bg-danger/90 shadow-sm shadow-danger/30"
          }`}
        >
          Review {side === "yes" ? "Buy" : "Sell"}
        </button>
      </div>
    </aside>
  );
}
