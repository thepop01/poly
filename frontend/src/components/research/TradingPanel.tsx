"use client";

import { useState } from "react";
import type { ResearchPosition } from "@/types/research";
import { TrendingUp, TrendingDown, Info } from "lucide-react";

interface TradingPanelProps {
  /** Selected position from PositionsBar */
  selectedPosition?: ResearchPosition;
  /** Whether this panel is visible */
  visible?: boolean;
  /** Toggle visibility */
  onToggle?: () => void;
}

type TradeSide = "yes" | "no";
type OrderType = "limit" | "market";

const SHARE_PRESETS = [10, 50, 100];

export default function TradingPanel({
  selectedPosition,
  visible = true,
  onToggle,
}: TradingPanelProps) {
  const [side, setSide] = useState<TradeSide>("yes");
  const [shares, setShares] = useState(10);
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [mockReviewed, setMockReviewed] = useState(false);

  if (!visible) {
    return (
      <aside className="trading-panel-hidden" aria-label="Trading panel collapsed">
        <button
          type="button"
          onClick={onToggle}
          className="trading-panel-toggle-btn"
          title="Show mock trading ticket"
          aria-label="Show mock trading ticket"
        >
          <TrendingUp size={14} />
        </button>
      </aside>
    );
  }

  const marketTitle = selectedPosition?.market_title ?? selectedPosition?.condition_id ?? null;
  const avgPrice = selectedPosition?.avg_price ?? null;
  const priceDisplay = avgPrice !== null ? `$${avgPrice.toFixed(2)}` : "—";
  const costDisplay = avgPrice !== null ? `$${(avgPrice * shares).toFixed(2)}` : "—";
  const payoutDisplay = avgPrice !== null ? `$${shares.toFixed(2)}` : "—";

  const handleReview = () => {
    // Purely local UI state — never calls an API or broker
    setMockReviewed(true);
  };

  return (
    <aside className="trading-panel" aria-label="Mock trading ticket">
      {/* Panel header */}
      <div className="trading-panel-header">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground">Mock order ticket</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-2 border border-border text-subtle uppercase">
            Preview only
          </span>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="trading-panel-close-btn"
          title="Collapse mock ticket"
          aria-label="Collapse mock ticket"
        >
          <TrendingDown size={12} />
        </button>
      </div>

      {/* Honest warning callout */}
      <div
        className="trading-mock-notice p-2.5 bg-surface-2/70 border-b border-border text-[11px] text-subtle flex items-start gap-1.5"
        role="note"
      >
        <Info size={13} className="text-primary mt-0.5 flex-shrink-0" />
        <span>
          Preview only. Order placement is not integrated and live trading is simulated.
        </span>
      </div>

      {/* Selected Market Title */}
      <div className="trading-strike p-3 border-b border-border/50">
        {marketTitle ? (
          <div>
            <p className="text-xs font-semibold text-foreground truncate" title={marketTitle}>
              {marketTitle}
            </p>
            {selectedPosition?.outcome && (
              <span className="text-[10px] font-mono text-subtle mt-0.5 inline-block">
                Target: {selectedPosition.outcome}
              </span>
            )}
          </div>
        ) : (
          <p className="text-xs text-subtle italic">Select a position to preview</p>
        )}
      </div>

      {/* Buy / Sell toggle */}
      <div className="trading-side-toggle">
        <button
          type="button"
          className={`trading-side-btn ${side === "yes" ? "trading-side-btn-yes active" : ""}`}
          onClick={() => {
            setSide("yes");
            setMockReviewed(false);
          }}
        >
          Buy
        </button>
        <button
          type="button"
          className={`trading-side-btn ${side === "no" ? "trading-side-btn-no active" : ""}`}
          onClick={() => {
            setSide("no");
            setMockReviewed(false);
          }}
        >
          Sell
        </button>
        <span className="trading-side-label">{orderType}</span>
      </div>

      {/* Outcome pills */}
      <div className="trading-price-row">
        <button
          type="button"
          onClick={() => {
            setSide("yes");
            setMockReviewed(false);
          }}
          className={`trading-price-pill trading-price-pill-yes ${side === "yes" ? "active" : ""}`}
        >
          YES
        </button>
        <button
          type="button"
          onClick={() => {
            setSide("no");
            setMockReviewed(false);
          }}
          className={`trading-price-pill trading-price-pill-no ${side === "no" ? "active" : ""}`}
        >
          NO
        </button>
      </div>

      {/* Account balance display (honest mock) */}
      <div className="trading-row-label">
        <span className="text-xs text-subtle">Predictions account</span>
        <span className="text-xs font-mono text-subtle">—</span>
      </div>

      {/* Shares presets and input */}
      <div className="trading-field-group">
        <label className="trading-field-label">Contracts</label>
        <div className="trading-shares-presets">
          {SHARE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => {
                setShares(preset);
                setMockReviewed(false);
              }}
              className={`trading-preset-btn ${shares === preset ? "active" : ""}`}
            >
              {preset}
            </button>
          ))}
        </div>
        <input
          type="number"
          value={shares}
          min={1}
          onChange={(e) => {
            setShares(Math.max(1, Number(e.target.value)));
            setMockReviewed(false);
          }}
          className="trading-input"
          aria-label="Number of contracts"
        />
      </div>

      {/* Price row */}
      <div className="trading-row-label">
        <label className="trading-field-label">Price</label>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setOrderType(orderType === "limit" ? "market" : "limit")}
            className={`trading-preset-btn text-xs ${orderType === "limit" ? "active" : ""}`}
          >
            {orderType.toUpperCase()}
          </button>
          <span className="text-xs font-mono text-foreground">{priceDisplay}</span>
        </div>
      </div>

      {/* Expiration */}
      <div className="trading-row-label">
        <label className="trading-field-label">Expiration</label>
        <span className="text-xs text-subtle font-mono">—</span>
      </div>

      {/* Summary */}
      <div className="trading-summary">
        <div className="trading-row-label">
          <span className="text-xs text-subtle">Estimated cost</span>
          <span className="text-xs font-mono text-foreground">{costDisplay}</span>
        </div>
        <div className="trading-row-label">
          <span className="text-xs text-subtle">Estimated payout</span>
          <span className="text-xs font-mono text-foreground">{payoutDisplay}</span>
        </div>
      </div>

      {/* Feedback banner if simulated */}
      {mockReviewed && (
        <div className="mx-3 my-1 p-2 rounded bg-primary/10 border border-primary/20 text-xs text-primary text-center">
          Mock order simulated (no live order placed)
        </div>
      )}

      {/* CTA button */}
      <div className="p-3 pt-2">
        <button
          type="button"
          onClick={handleReview}
          className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-all duration-150 cursor-pointer ${
            side === "yes"
              ? "bg-success hover:bg-success/90 shadow-sm shadow-success/30"
              : "bg-danger hover:bg-danger/90 shadow-sm shadow-danger/30"
          }`}
        >
          Review mock order
        </button>
      </div>
    </aside>
  );
}
