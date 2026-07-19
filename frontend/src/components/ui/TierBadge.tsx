"use client";

/**
 * Wallet-quality tier badge: TIER 2 (curated) = filled green pill,
 * TIER 1 (global) = gray pill. Anything else renders muted.
 */
export function TierBadge({ tier }: { tier?: string | number | null }) {
  if (tier === null || tier === undefined || tier === "") return null;
  const normalized = String(tier).replace(/tier\s*/i, "").trim();

  const isCurated = normalized === "2";
  const isGlobal = normalized === "1";

  const className = isCurated
    ? "bg-primary/90 text-background"
    : isGlobal
      ? "bg-surface-3 text-muted-fg"
      : "bg-surface-2 text-subtle border border-border";

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full font-mono text-[10px] font-bold uppercase tracking-wider whitespace-nowrap ${className}`}
    >
      Tier {normalized}
    </span>
  );
}
