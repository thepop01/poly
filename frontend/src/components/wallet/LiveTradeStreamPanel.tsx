"use client";

import React, { useState } from "react";
import { Zap, RotateCw } from "lucide-react";
import { formatCurrency, formatAddress, timeAgo } from "@/utils/format";

export interface TradeItem {
  id?: string;
  market?: string;
  market_title?: string;
  title?: string;
  side?: string;
  outcome?: string;
  price?: number | string;
  size?: number | string;
  tokens?: number | string;
  amount?: number | string;
  amount_usd?: number | string;
  timestamp?: number | string;
  user?: string;
  address?: string;
}

interface LiveTradeStreamPanelProps {
  trades: TradeItem[];
  walletAddress?: string;
  onRefresh?: () => void;
  loading?: boolean;
}

const TRADES_PAGE_SIZE = 10;

export function LiveTradeStreamPanel({
  trades,
  walletAddress,
  onRefresh,
  loading = false,
}: LiveTradeStreamPanelProps) {
  const [currentPage, setCurrentPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(trades.length / TRADES_PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedTrades = trades.slice(
    (safePage - 1) * TRADES_PAGE_SIZE,
    safePage * TRADES_PAGE_SIZE
  );

  return (
    <div className="flex flex-col bg-surface border border-border rounded-2xl shadow-xs overflow-hidden">
      {/* Panel Header */}
      <div className="px-4 py-3 bg-surface-2/40 border-b border-border flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Zap size={14} className="text-emerald-500 fill-emerald-500/20" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Live Trade Stream
          </h3>
          <span className="px-2 py-0.5 rounded-md bg-surface border border-border text-muted-fg text-[10px] font-mono font-semibold">
            {trades.length > 0 ? `${trades.length} RECENT` : "LIVE"}
          </span>
        </div>

        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={loading}
            className="p-1 rounded-md text-muted-fg hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer disabled:opacity-50"
            title="Refresh stream"
          >
            <RotateCw size={13} className={loading ? "animate-spin text-primary" : ""} />
          </button>
        )}
      </div>

      {/* Trades List (10 trades max per page) */}
      <div className="divide-y divide-border/50 p-2 space-y-1 overflow-y-auto max-h-[520px]">
        {loading && trades.length === 0 ? (
          <div className="space-y-2 p-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-12 rounded-xl skeleton" />
            ))}
          </div>
        ) : pagedTrades.length === 0 ? (
          <div className="py-12 text-center text-muted-fg text-xs font-medium">
            No recent trade activity recorded.
          </div>
        ) : (
          pagedTrades.map((t, idx) => {
            const side = (t.side || "BUY").toUpperCase();
            const isBuy = side === "BUY";
            const priceNum = t.price ? Number(t.price) : null;
            const priceCents = priceNum != null ? `${(priceNum * 100).toFixed(1)}¢` : null;
            const tokenAmount = t.tokens ?? t.size;
            const tokenFormatted =
              tokenAmount != null && !isNaN(Number(tokenAmount))
                ? Number(tokenAmount).toLocaleString(undefined, { maximumFractionDigits: 1 })
                : "—";

            const usdVal =
              t.amount_usd ??
              t.amount ??
              (Number(tokenAmount) && priceNum ? Number(tokenAmount) * priceNum : null);

            const title = t.title || t.market_title || t.market || "Market Trade";
            const addr = t.address || t.user || walletAddress || "";
            const tAgo = t.timestamp ? timeAgo(t.timestamp)?.relative : "Just now";

            return (
              <div
                key={t.id || idx}
                className="p-2 rounded-xl hover:bg-surface-2/60 transition-colors flex items-start justify-between gap-2.5 text-xs"
              >
                {/* Left Side Pill + Market info */}
                <div className="flex items-start gap-2 min-w-0">
                  {/* Buy / Sell Badge */}
                  <div
                    className={`flex flex-col items-center justify-center px-1.5 py-0.5 rounded-md font-mono font-bold text-[9px] flex-shrink-0 ${
                      isBuy
                        ? "bg-green-500/10 text-green-600 border border-green-500/20"
                        : "bg-red-500/10 text-red-600 border border-red-500/20"
                    }`}
                  >
                    <span>{side}</span>
                    {priceCents && <span className="text-[8px] opacity-85">{priceCents}</span>}
                  </div>

                  {/* Market Title & Address */}
                  <div className="min-w-0">
                    <p
                      className="font-medium text-foreground text-xs leading-snug line-clamp-1 truncate max-w-[170px]"
                      title={title}
                    >
                      {title}
                    </p>
                    <span className="text-[9px] font-mono text-muted-fg mt-0.5 block truncate">
                      {formatAddress(addr)}
                    </span>
                  </div>
                </div>

                {/* Right Side Stats */}
                <div className="text-right flex-shrink-0 font-mono">
                  <div className="font-bold text-foreground text-xs">
                    {usdVal != null ? formatCurrency(Number(usdVal)) : "—"}
                  </div>
                  <div className="text-[9px] text-muted-fg">
                    {tokenFormatted} <span className="text-[8px]">TOKENS</span>
                  </div>
                  <div className="text-[8.5px] text-muted-fg">{tAgo}</div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Pagination Footer */}
      {trades.length > TRADES_PAGE_SIZE && (
        <div className="px-3 py-2 bg-surface-2/40 border-t border-border flex items-center justify-between flex-shrink-0">
          <span className="text-[10px] text-muted-fg font-mono">
            {trades.length} total
          </span>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={safePage <= 1}
              className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface border border-border hover:bg-surface-2 text-muted-fg hover:text-foreground transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Prev
            </button>
            <span className="text-[10px] text-muted-fg font-mono">
              Page {safePage} of {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={safePage >= totalPages}
              className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface border border-border hover:bg-surface-2 text-muted-fg hover:text-foreground transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
