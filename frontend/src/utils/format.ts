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

/** Coerce a possibly-stringified numeric into a number or null. */
export function toNum(v: string | number | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isNaN(n) ? null : n;
}

export function timeAgo(value?: string | null): { relative: string; absolute: string } | null {
  if (!value) return null;
  const d = new Date(value);
  const diffMs = Date.now() - d.getTime();
  const diffHrs = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHrs / 24);
  let relative = "";
  if (diffHrs < 1) relative = "Just now";
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
