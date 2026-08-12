"use client";

/**
 * Wallet-quality tier badge:
 * Supports CURATED, STANDARD, NEW, LOW_BALANCE, DEAD, UNCLASSIFIED, and numeric size tiers (1..4).
 */
export function TierBadge({ tier }: { tier?: string | number | null }) {
  if (tier === null || tier === undefined || tier === "") {
    return <span className="text-subtle font-mono text-xs">—</span>;
  }

  const raw = String(tier).trim();
  const uppercase = raw.toUpperCase();

  let label = raw;
  let className = "bg-surface-2 text-subtle border border-border";

  if (uppercase === "CURATED" || uppercase === "2" || uppercase === "TIER 2") {
    label = "CURATED";
    className = "bg-primary/90 text-background font-bold";
  } else if (uppercase === "STANDARD" || uppercase === "1" || uppercase === "TIER 1") {
    label = "STANDARD";
    className = "bg-surface-3 text-foreground border border-border font-medium";
  } else if (uppercase === "NEW") {
    label = "NEW";
    className = "bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium";
  } else if (uppercase === "LOW_BALANCE" || uppercase === "LOW BAL") {
    label = "LOW BAL";
    className = "bg-amber-500/20 text-amber-400 border border-amber-500/30 font-medium";
  } else if (uppercase === "DEAD") {
    label = "DEAD";
    className = "bg-red-500/20 text-red-400 border border-red-500/30 font-medium";
  } else if (uppercase === "UNCLASSIFIED") {
    label = "QUEUED";
    className = "bg-surface-2 text-subtle border border-border font-normal";
  } else if (/^TIER\s*\d+$/i.test(raw) || /^\d+$/.test(raw)) {
    const num = raw.replace(/tier\s*/i, "").trim();
    label = `Tier ${num}`;
    if (num === "4") className = "bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold";
    else if (num === "3") className = "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-bold";
    else if (num === "2") className = "bg-primary/90 text-background font-bold";
    else className = "bg-surface-3 text-foreground border border-border font-medium";
  }

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full font-mono text-[10px] uppercase tracking-wider whitespace-nowrap ${className}`}
    >
      {label}
    </span>
  );
}

