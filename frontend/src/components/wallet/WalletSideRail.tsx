"use client";

import React from "react";
import { Wallet, BarChart3, Trophy } from "lucide-react";
import { formatCurrency, formatPercent } from "@/utils/format";

/* ── Validated palette (light surface #FFFFFF): emerald #059669 · blue #2563EB · amber #D97706 ── */
const BAR_COLORS = ["#059669", "#2563EB", "#D97706"];

interface CategoryRow {
  category: string;
  subcategory?: string | null;
  pnl?: number | null;
  roi_pct?: number | null;
  win_rate?: number | string | null;
  resolved_count?: number | string | null;
  winning_count?: number | string | null;
}

/**
 * Right-rail widget: compact wallet snapshot + top categories by ROI.
 * Fills the vertical gap below the Live Trade Stream using data already
 * fetched by the wallet profile page — no new API calls.
 */
export function WalletSideRail({
  tier,
  pnl,
  winRate,
  winningCount,
  losingCount,
  volume,
  roiPct,
  balance,
  depositsTotal,
  favoriteCount,
  positionsCount,
  positionValue,
  loading = false,
  categories = [],
}: {
  tier?: string;
  pnl?: number | null;
  winRate?: number | null;
  winningCount?: number | string | null;
  losingCount?: number | string | null;
  volume?: number | null;
  roiPct?: number | null;
  balance?: number | null;
  depositsTotal?: number | null;
  favoriteCount?: number;
  positionsCount?: number;
  positionValue?: number | null;
  loading?: boolean;
  categories?: CategoryRow[];
}) {
  // All non-OVERALL categories by trade count. Dedupe to root row per category.
  const allCategories = [...categories]
    .filter((c) => (c.category || "").toUpperCase() !== "OVERALL")
    .filter((c) => (Number(c.resolved_count) || 0) > 0)
    .sort((a, b) => {
      const catCmp = a.category.localeCompare(b.category);
      if (catCmp !== 0) return catCmp;
      const aRoot = !a.subcategory ? 0 : 1;
      const bRoot = !b.subcategory ? 0 : 1;
      return aRoot - bRoot;
    })
    .filter((c, i, arr) => i === 0 || arr[i - 1].category !== c.category)
    .sort((a, b) => (Number(b.resolved_count) || 0) - (Number(a.resolved_count) || 0));

  const maxTrades = Math.max(...allCategories.map((c) => Number(c.resolved_count) || 0), 1);

  const fmtSigned = (v: number | null | undefined) => {
    if (v == null) return "—";
    return `${v > 0 ? "+" : ""}${formatCurrency(v)}`;
  };

  return (
    <div className="space-y-5">
      {/* ── Wallet Snapshot mini-card ───────────────────────────────── */}
      <div className="bg-surface border border-border rounded-2xl shadow-xs overflow-hidden">
        <div className="px-4 py-2.5 bg-surface-2/40 border-b border-border flex items-center gap-2">
          <Wallet size={13} className="text-primary" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">Snapshot</h3>
        </div>

        {/* Hero Area: Polymarket PnL + Watchlist Adds */}
        <div className="px-4 pt-3 pb-2.5 border-b border-border/60 flex items-center justify-between gap-3">
          <div>
            <span className="block text-[10px] uppercase tracking-wide text-muted-fg font-medium">Polymarket PnL</span>
            {loading ? (
              <span className="block h-6 w-24 rounded skeleton mt-1" />
            ) : (
              <span className={`block text-lg font-bold tabular-nums ${pnl != null && pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                {fmtSigned(pnl)}
              </span>
            )}
          </div>
          <div className="text-right">
            <span className="block text-[10px] uppercase tracking-wide text-muted-fg font-medium">Watchlist Adds</span>
            {loading ? (
              <span className="block h-6 w-12 rounded skeleton mt-1 ml-auto" />
            ) : (
              <span className="block text-lg font-bold font-mono tabular-nums text-foreground">
                {favoriteCount ?? 0}
              </span>
            )}
          </div>
        </div>

        <div className="p-4 grid grid-cols-2 gap-x-3 gap-y-3">
          {[
            {
              label: "Win Rate",
              value: winRate != null
                ? `${Number(winRate).toFixed(1)}%`
                : (winningCount != null && losingCount != null
                  ? `${((Number(winningCount) / Math.max(1, Number(winningCount) + Number(losingCount))) * 100).toFixed(1)}%`
                  : "—"),
              color: winRate != null ? (Number(winRate) >= 50 ? "text-green-600" : "text-red-500") : undefined,
            },
            { label: "W / L", value: winningCount != null ? `${winningCount} / ${losingCount ?? 0}` : "—" },
            {
              label: "Volume",
              value: volume != null ? formatCurrency(volume) : "—",
            },
            {
              label: "ROI",
              value: roiPct != null ? `${roiPct > 0 ? "+" : ""}${Number(roiPct).toFixed(1)}%` : "—",
              color: roiPct != null ? (Number(roiPct) >= 0 ? "text-green-600" : "text-red-500") : undefined,
            },
            {
              label: "Balance",
              value: balance != null ? formatCurrency(balance) : "—",
            },
            {
              label: "Open Positions",
              value: `${positionsCount ?? 0} · ${positionValue != null ? formatCurrency(positionValue) : "$0"}`,
            },
            { label: "Tier", value: tier || "—" },
            { label: "Deposits", value: depositsTotal != null ? formatCurrency(depositsTotal) : "—" },
          ].map(({ label, value, color }) => (
            <div key={label}>
              <span className="block text-[10px] uppercase tracking-wide text-muted-fg">{label}</span>
              {loading ? (
                <span className="block h-4 w-16 rounded skeleton mt-0.5" />
              ) : (
                <span className={`block text-xs font-bold font-mono tabular-nums truncate ${color || "text-foreground"}`} title={value}>{value}</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Category · Trades & Win Rate ──────────────────────────── */}
      <div className="bg-surface border border-border rounded-2xl shadow-xs overflow-hidden">
        <div className="px-4 py-2.5 bg-surface-2/40 border-b border-border flex items-center gap-2">
          <BarChart3 size={13} className="text-primary" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">Category · Trades & Win Rate</h3>
        </div>
        <div className="p-3 space-y-2.5 max-h-[380px] overflow-y-auto">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-8 rounded-lg skeleton" />)
          ) : allCategories.length === 0 ? (
            <div className="py-6 text-center text-muted-fg text-xs">No category data yet.</div>
          ) : (
            allCategories.map((c, i) => {
              const trades = Number(c.resolved_count) || 0;
              const wins = Number(c.winning_count) || (c.win_rate != null && trades > 0 ? Math.round((Number(c.win_rate) / 100) * trades) : 0);
              const winRate = c.win_rate != null ? Number(c.win_rate) : (trades > 0 ? (wins / trades) * 100 : 0);
              const pctWidth = (trades / maxTrades) * 100;
              return (
                <div key={c.category} className="space-y-1">
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="font-semibold text-foreground truncate flex items-center gap-1.5 min-w-0">
                      <Trophy size={10} className={i === 0 ? "text-primary flex-shrink-0" : "text-muted-fg/40 flex-shrink-0"} />
                      <span className="truncate">{c.category}</span>
                    </span>
                    <span className="font-mono text-[10px] tabular-nums flex-shrink-0 text-muted-fg whitespace-nowrap">
                      <span className="font-bold text-foreground">{trades}</span> trades
                      <span className="mx-1 text-muted-fg/60">·</span>
                      <span className="font-bold text-foreground">{wins}</span> wins
                      <span className="mx-1 text-muted-fg/60">·</span>
                      <span className={`font-bold ${winRate >= 50 ? "text-green-600" : "text-red-500"}`}>
                        {winRate.toFixed(2)}%
                      </span>
                    </span>
                  </div>
                  {/* Thin meter — fill = trade volume share; win rate shown as text value */}
                  <div className="h-1.5 w-full rounded-full bg-surface-2 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{
                        width: `${Math.max(4, pctWidth)}%`,
                        backgroundColor: BAR_COLORS[i % BAR_COLORS.length],
                      }}
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
