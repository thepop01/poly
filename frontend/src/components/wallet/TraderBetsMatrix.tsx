"use client";

import React from "react";
import { SlidersHorizontal } from "lucide-react";

export interface PriceBucketData {
  label: string;
  buys: number;
  wins: number;
  avgSell?: number | null;
}

interface TraderBetsMatrixProps {
  buckets: PriceBucketData[];
}

export function TraderBetsMatrix({ buckets }: TraderBetsMatrixProps) {
  const maxBuys = Math.max(...buckets.map((b) => b.buys), 1);

  return (
    <div className="card p-5 rounded-2xl border border-border shadow-xs flex flex-col justify-between space-y-4 bg-surface h-full">
      {/* Card Header */}
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={14} className="text-foreground" />
        <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
          Where This Trader Bets
        </h3>
      </div>

      {/* 6 Price Bucket Columns */}
      <div className="grid grid-cols-6 gap-1.5 sm:gap-3 divide-x divide-border/60">
        {buckets.map((b, colIdx) => {
          const winRate = b.buys > 0 ? Math.round((b.wins / b.buys) * 100) : 0;

          // 3 cols x 6 rows = 18 dots max grid
          const maxDots = 18;
          const totalDots =
            b.buys === 0
              ? 0
              : Math.max(1, Math.min(maxDots, Math.round((b.buys / maxBuys) * maxDots)));

          const winDots =
            totalDots > 0
              ? Math.max(b.wins > 0 ? 1 : 0, Math.round((b.wins / b.buys) * totalDots))
              : 0;

          const dotsGrid = [];
          for (let i = 0; i < maxDots; i++) {
            if (i < winDots) {
              dotsGrid.push("win");
            } else if (i < totalDots) {
              dotsGrid.push("fill");
            } else {
              dotsGrid.push("empty");
            }
          }

          return (
            <div
              key={colIdx}
              className={`flex flex-col justify-between ${colIdx > 0 ? "pl-2 sm:pl-3" : ""}`}
            >
              {/* Header: Range label & Win Rate */}
              <div className="text-center">
                <span className="text-[11px] font-semibold text-foreground font-mono block">
                  {b.label}
                </span>
                <span className="text-sm sm:text-base font-extrabold font-mono text-foreground block mt-0.5">
                  {winRate}%
                </span>
              </div>

              {/* Dot Matrix Visualizer */}
              <div className="h-16 flex items-center justify-center my-2">
                <div className="grid grid-cols-6 gap-1 p-1 rounded-md bg-surface-2/40">
                  {dotsGrid.map((type, dIdx) => (
                    <div
                      key={dIdx}
                      className={`w-1.5 h-1.5 rounded-full transition-all ${
                        type === "win"
                          ? "bg-slate-900"
                          : type === "fill"
                          ? "bg-slate-400"
                          : "opacity-0"
                      }`}
                    />
                  ))}
                </div>
              </div>

              {/* Counts */}
              <div className="text-[10px] font-mono text-muted-fg space-y-0.5 mt-auto">
                <div className="flex justify-between">
                  <span>Fills:</span>
                  <span className="font-semibold text-foreground">{b.buys}</span>
                </div>
                <div className="flex justify-between">
                  <span>Wins:</span>
                  <span className="font-semibold text-foreground">{b.wins}</span>
                </div>
              </div>

              {/* Avg Sell */}
              <div className="mt-2.5 pt-2 border-t border-border/40 text-[10px] font-mono text-muted-fg">
                <span className="block text-[9px] text-muted-fg">Avg Sell:</span>
                <span className="font-bold text-foreground block mt-0.5">
                  {b.avgSell && b.avgSell > 0 ? `${(b.avgSell * 100).toFixed(1)}¢` : "—"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
