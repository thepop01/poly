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
    className = "bg-surface-2 text-foreground border border-border font-bold";
  } else if (uppercase === "STANDARD" || uppercase === "1" || uppercase === "TIER 1") {
    label = "STANDARD";
    className = "bg-surface-2 text-muted-fg border border-border font-medium";
  } else if (uppercase === "NEW") {
    label = "NEW";
    className = "bg-surface-2 text-muted-fg border border-border font-medium";
  } else if (uppercase === "LOW_BALANCE" || uppercase === "LOW BAL") {
    label = "LOW BAL";
    className = "bg-surface-2 text-muted-fg border border-border font-medium";
  } else if (uppercase === "DEAD") {
    label = "DEAD";
    className = "bg-surface-2 text-muted-fg border border-border font-medium";
  } else if (uppercase === "UNCLASSIFIED") {
    label = "QUEUED";
    className = "bg-surface-2 text-muted-fg border border-border font-normal";
  } else if (/^TIER\s*\d+$/i.test(raw) || /^\d+$/.test(raw)) {
    const num = raw.replace(/tier\s*/i, "").trim();
    label = `Tier ${num}`;
    className = "bg-surface-2 text-foreground border border-border font-medium";
  }

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full font-mono text-[10px] uppercase tracking-wider whitespace-nowrap ${className}`}
    >
      {label}
    </span>
  );
}
