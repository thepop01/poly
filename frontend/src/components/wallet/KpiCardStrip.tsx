"use client";

import React, { useMemo } from "react";
import { formatCurrency, formatPercent } from "@/utils/format";

interface KpiCardStripProps {
  pnl?: number | null;
  pnlWindows?: Array<{ label: string; value: number | null }>;
  winRate?: number | null;
  winningCount?: number | null;
  losingCount?: number | null;
  volume?: number | null;
  roiPct?: number | null;
  balance?: number | null;
  positionsCount?: number;
  positionValue?: number | null;
  loading?: boolean;
}

export function KpiCardStrip({
  pnl = 0,
  pnlWindows = [],
  winRate,
  winningCount,
  losingCount,
  volume,
  roiPct,
  balance,
  positionsCount = 0,
  positionValue,
  loading = false,
}: KpiCardStripProps) {
  const currentPnl = pnl ?? 0;
  const isPnlPositive = currentPnl >= 0;

  // Mini sparkline points for Total PNL — only real window values, no fabrication
  const sparklineData = useMemo(() => {
    const validWindows = pnlWindows
      .filter((w) => w.value != null && !isNaN(Number(w.value)))
      .map((w) => Number(w.value));

    // Not enough real data to draw a meaningful sparkline
    if (validWindows.length < 2) {
      return { pointsStr: "", lastPoint: null as [string, string] | null };
    }

    const values = [...validWindows].reverse();

    const min = Math.min(...values, 0);
    const max = Math.max(...values, 0);
    const range = max - min || 1;
    const width = 64;
    const height = 24;

    const points = values.map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const last = points[points.length - 1].split(",");
    return {
      pointsStr: points.join(" "),
      lastPoint: last as [string, string],
    };
  }, [pnlWindows]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-24 rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between"
          >
            <div className="w-16 h-3 rounded skeleton" />
            <div className="w-24 h-6 rounded skeleton my-1" />
            <div className="w-20 h-2.5 rounded skeleton" />
          </div>
        ))}
      </div>
    );
  }

  // Win rate calculation — null winRate renders as "—" with an empty ring
  const hasWinRate = winRate != null && !isNaN(Number(winRate));
  const wrNum = hasWinRate ? Number(winRate) : 0;
  const circumference = 2 * Math.PI * 13;
  const strokeDashoffset = hasWinRate
    ? circumference - (Math.min(100, Math.max(0, wrNum)) / 100) * circumference
    : circumference;

  // Open position value display
  let openPosDisplay = "—";
  if (positionValue != null && positionValue > 0) {
    if (positionValue < 1) {
      openPosDisplay = `${(positionValue * 100).toFixed(1)}¢`;
    } else {
      openPosDisplay = formatCurrency(positionValue);
    }
  } else if (positionsCount > 0) {
    openPosDisplay = `${positionsCount}`;
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
      {/* 1. TOTAL PNL */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          TOTAL PNL
        </span>
        <div className="flex items-end justify-between gap-2 my-1">
          <span
            className={`text-xl sm:text-[22px] font-extrabold font-mono tracking-tight ${
              isPnlPositive ? "text-green-500" : "text-red-500"
            }`}
          >
            {isPnlPositive ? "+" : ""}
            {formatCurrency(currentPnl)}
          </span>
          {/* Mini Sparkline SVG */}
          <div className="w-16 h-6 flex-shrink-0 select-none pb-0.5">
            {sparklineData.pointsStr ? (
              <svg viewBox="0 0 64 24" className="w-full h-full overflow-visible">
                <polyline
                  fill="none"
                  stroke={isPnlPositive ? "#22c55e" : "#ef4444"}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  points={sparklineData.pointsStr}
                />
                {sparklineData.lastPoint && (
                  <circle
                    cx={sparklineData.lastPoint[0]}
                    cy={sparklineData.lastPoint[1]}
                    r="2.5"
                    fill={isPnlPositive ? "#22c55e" : "#ef4444"}
                  />
                )}
              </svg>
            ) : null}
          </div>
        </div>
        <span className="text-[10px] text-muted-fg font-medium truncate">
          All-time realized & CTF
        </span>
      </div>

      {/* 2. WIN RATE */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          WIN RATE
        </span>
        <div className="flex items-center justify-between gap-2 my-1">
          <span className="text-xl sm:text-[22px] font-extrabold font-mono text-foreground tracking-tight">
            {hasWinRate ? formatPercent(wrNum) : "—"}
          </span>
          {/* Circular Progress Ring */}
          <div className="w-8 h-8 relative flex items-center justify-center flex-shrink-0">
            <svg className="w-8 h-8 -rotate-90">
              <circle
                cx="16"
                cy="16"
                r="13"
                className="stroke-surface-2"
                strokeWidth="3"
                fill="none"
              />
              <circle
                cx="16"
                cy="16"
                r="13"
                className="stroke-green-500 transition-all duration-500 ease-out"
                strokeWidth="3"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="none"
              />
            </svg>
          </div>
        </div>
        <span className="text-[10px] text-muted-fg font-mono font-medium">
          {winningCount != null && losingCount != null
            ? `${winningCount}W / ${losingCount}L`
            : "—"}
        </span>
      </div>

      {/* 3. VOLUME */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          VOLUME
        </span>
        <div className="flex items-end justify-between gap-2 my-1">
          <span className="text-xl sm:text-[22px] font-extrabold font-mono text-foreground tracking-tight">
            {volume != null ? formatCurrency(volume) : "—"}
          </span>
          {/* Mini Bar Histogram */}
          <div className="flex items-end gap-1 h-5 pb-0.5 select-none">
            <div className="w-1.5 h-2 bg-slate-300 rounded-xs" />
            <div className="w-1.5 h-3.5 bg-slate-400 rounded-xs" />
            <div className="w-1.5 h-5 bg-slate-500 rounded-xs" />
            <div className="w-1.5 h-3 bg-slate-400 rounded-xs" />
            <div className="w-1.5 h-4.5 bg-slate-600 rounded-xs" />
          </div>
        </div>
        <span className="text-[10px] text-muted-fg font-medium truncate">
          Cumulative betting
        </span>
      </div>

      {/* 4. ROI */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          ROI
        </span>
        <div className="flex items-end justify-between gap-2 my-1">
          <span className="text-xl sm:text-[22px] font-extrabold font-mono text-foreground tracking-tight">
            {roiPct != null ? `${roiPct > 0 ? "+" : ""}${roiPct.toFixed(2)}%` : "0.00%"}
          </span>
          {/* Mini Line Wave */}
          <div className="w-12 h-4 select-none flex items-center justify-end pb-1">
            <svg viewBox="0 0 48 12" className="w-full h-full overflow-visible">
              <path
                d="M 0 6 Q 12 6, 24 6 T 48 6"
                fill="none"
                stroke="#22c55e"
                strokeWidth="2"
                strokeLinecap="round"
              />
              <circle cx="48" cy="6" r="2" fill="#22c55e" />
            </svg>
          </div>
        </div>
        <span className="text-[10px] text-muted-fg font-medium truncate">
          PnL / Capital ratio
        </span>
      </div>

      {/* 5. BALANCE */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          BALANCE
        </span>
        <div className="my-1">
          <span className="text-xl sm:text-[22px] font-extrabold font-mono text-foreground tracking-tight">
            {balance != null ? formatCurrency(balance) : "—"}
          </span>
        </div>
        <span className="text-[10px] text-muted-fg font-medium truncate">
          Live portfolio cash
        </span>
      </div>

      {/* 6. OPEN POSITIONS */}
      <div className="rounded-xl border border-border bg-surface p-3.5 flex flex-col justify-between shadow-xs hover:border-border-2 transition-all">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted-fg">
          OPEN POSITIONS
        </span>
        <div className="my-1">
          <span className="text-xl sm:text-[22px] font-extrabold font-mono text-foreground tracking-tight">
            {openPosDisplay}
          </span>
        </div>
        <span className="text-[10px] text-muted-fg font-medium truncate">
          {positionsCount > 0 ? `${positionsCount} active bets` : "Active bets"}
        </span>
      </div>
    </div>
  );
}
