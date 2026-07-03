export function formatCurrency(value?: number) {
  if (!value) return "$0";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1).replace(/\.0$/, '')}k`;
  return `${sign}$${abs.toFixed(0)}`;
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
