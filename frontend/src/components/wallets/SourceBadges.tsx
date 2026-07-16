"use client";

import { Flame } from "lucide-react";

export const SOURCE_LABELS: Record<string, { label: string; className: string }> = {
  trade: { label: "Trade", className: "bg-orange-500/10 text-orange-400 border border-orange-500/20" },
  deposit: { label: "Deposit", className: "bg-blue-500/10 text-blue-400 border border-blue-500/20" },
  leaderboard: { label: "Leaderboard", className: "bg-purple-500/10 text-purple-400 border border-purple-500/20" },
  custom: { label: "Custom", className: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" },
};

export function SourceBadges({ sources }: { sources?: string[] | null }) {
  if (!sources || sources.length === 0) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-surface-2 text-muted-fg border border-border">
        Unknown
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 flex-wrap justify-end">
      {sources.map((source) => {
        const config = SOURCE_LABELS[source.toLowerCase()] || {
          label: source,
          className: "bg-surface-2 text-muted-fg border border-border",
        };
        return (
          <span
            key={source}
            className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${config.className}`}
          >
            {config.label}
          </span>
        );
      })}
    </span>
  );
}

export function MightCookBadge({ mightCookType }: { mightCookType?: string | null }) {
  if (!mightCookType) return null;
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20"
      title="Deposited ≥ $5k with 0 trades"
    >
      <Flame size={10} />
      Might Cook
    </span>
  );
}
