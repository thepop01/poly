export function formatCurrency(value?: number) {
  if (!value) return "$0";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function formatAddress(addr: string) {
  if (!addr) return "Unknown";
  if (addr.length < 10) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

/** Signed currency string, e.g. "+$1.91M" / "-$4.2k". */
export function formatSignedCurrency(value?: number | string | null): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${formatCurrency(n)}`;
}

/**
 * Formats a percentage cleanly (e.g. win rate).
 * Backend stores all percentages on a 0-100 scale.
 */
export function formatPercent(value?: number | string | null, decimals = 1): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(String(value));
  if (Number.isNaN(n)) return "—";
  return `${n.toFixed(decimals)}%`;
}

/**
 * Formats a prediction market price into cents (e.g. 45¢ or 99.2¢).
 * Strictly guards against rounding up to 100¢.
 */
export function formatPriceCents(value?: number | string | null): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(String(value));
  if (Number.isNaN(n) || n <= 0) return "—";
  const cents = n <= 1.0 ? n * 100 : n;
  if (cents >= 99.9) return "99.9¢";
  if (cents >= 99.0) return `${cents.toFixed(1)}¢`;
  return `${cents.toFixed(0)}¢`;
}

/** Coerce a possibly-stringified numeric into a number or null. */
export function toNum(v: string | number | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isNaN(n) ? null : n;
}

export function timeAgo(value?: string | number | null): { relative: string; absolute: string } | null {
  if (value == null || value === "") return null;
  let d: Date;
  if (typeof value === "number") {
    // If timestamp is in seconds (< 100 billion), convert to milliseconds
    d = new Date(value < 1e11 ? value * 1000 : value);
  } else {
    const trimmed = String(value).trim();
    // Check if numeric string representing seconds
    if (/^\d{9,10}$/.test(trimmed)) {
      d = new Date(parseInt(trimmed, 10) * 1000);
    } else if (/^\d{12,13}$/.test(trimmed)) {
      d = new Date(parseInt(trimmed, 10));
    } else {
      d = new Date(trimmed);
    }
  }

  if (isNaN(d.getTime())) return null;

  const diffMs = Date.now() - d.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHrs = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHrs / 24);

  let relative = "";
  if (diffSecs < 60) relative = "Just now";
  else if (diffMins < 60) relative = `${diffMins}m ago`;
  else if (diffHrs < 24) relative = `${diffHrs}h ago`;
  else if (diffDays < 30) relative = `${diffDays}d ago`;
  else relative = d.toLocaleDateString();

  return { relative, absolute: d.toLocaleString() };
}


export function parseMarketMatch(question: string) {
  const clean = question.replace(/^will\s+/i, "").replace(/\?$/, "");
  const parts = clean.split(/\s+(?:vs\.?|v\.?|versus|beat|defeat)\s+/i);
  if (parts.length < 2) return null;
  return {
    team_home: parts[0].trim(),
    team_away: parts.slice(1).join(" vs ").trim(),
  };
}
