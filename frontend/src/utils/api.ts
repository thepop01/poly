export type PolymarketFixture = {
  event_id: string;
  market_id: string;
  team_home: string;
  team_away: string;
  sport: string;
  league: string;
  kickoff_time: string;       // actual match start time
  resolution_time: string | null;  // market close time
  volume: number;
  slug: string;
  source: "polymarket";
  is_prop: boolean;
  question: string;
  tags: string[];
  live_odds?: { outcome: string; price: number }[];
};

export function getAuthToken(): string | null {
  if (typeof window !== "undefined") {
    return localStorage.getItem("poly_auth_token");
  }
  return null;
}

export async function fetchAuthData(endpoint: string, options: RequestInit = {}) {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const url = `${process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'}${endpoint}`;

  const res = await fetch(url, {
    ...options,
    headers,
  });

  if (!res.ok) {
    // Attempt to parse error
    let errorMessage = `API error: ${res.status}`;
    try {
      const errData = await res.json();
      if (errData && errData.detail) {
        errorMessage = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
      }
    } catch (e) {
      // Ignore json parse error
    }
    throw new Error(errorMessage);
  }

  return res.json();
}



export async function getNewMarkets(limit = 50) {
  return fetchAuthData(`/api/tracker/new-markets?limit=${limit}`);
}

export async function getSmartMoneyAlerts(limit = 50, offset = 0, type?: 'LARGE_TRADE' | 'LARGE_DEPOSIT', tier?: string, category?: string, subcategory?: string) {
  let url = `/api/v2/alpha-calls/smart-money?limit=${limit}&offset=${offset}`;
  if (type) {
    url += `&alert_type=${type}`;
  }
  if (tier && tier !== 'all') {
    url += `&tier=${encodeURIComponent(tier)}`;
  }
  if (category && category !== 'all') {
    url += `&category=${encodeURIComponent(category)}`;
  }
  if (subcategory && subcategory !== 'all') {
    url += `&subcategory=${encodeURIComponent(subcategory)}`;
  }
  return fetchAuthData(url);
}

export async function getWhales(limit = 50) {
  return fetchAuthData(`/api/tracker/whales?limit=${limit}`);
}

export async function getWalletStats(address: string) {
  return fetchAuthData(`/api/v2/wallets/${address}/stats`);
}

export async function getWalletTrades(address: string, limit = 50) {
  return fetchAuthData(`/api/v2/wallets/${address}/trades?limit=${limit}`);
}

export async function getWalletPositions(address: string) {
  return fetchAuthData(`/api/v2/wallets/${address}/positions`);
}

export async function getWalletPnlChart(address: string) {
  return fetchAuthData(`/api/v2/wallets/${address}/pnl-chart`);
}

export async function toggleWatchlist(address: string, action: 'add' | 'remove') {
  if (action === 'add') {
    return fetchAuthData(`/api/watchlist/${address}`, {
      method: 'POST'
    });
  } else {
    return fetchAuthData(`/api/watchlist/${address}`, {
      method: 'DELETE'
    });
  }
}

export async function globalSearch(query: string) {
  return fetchAuthData(`/api/search?q=${encodeURIComponent(query)}`);
}

export interface WalletListParams {
  tab: 'all' | 'standard' | 'low_balance' | 'new' | 'hibernated';
  source?: string;
  search?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export async function getWalletList(p: WalletListParams) {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(p)
        .filter(([, v]) => v != null && v !== '')
        .map(([k, v]) => [k, String(v)])
    )
  );
  return fetchAuthData(`/api/v2/leaderboard/wallets?${qs}`);
}

export async function getWalletCounts() {
  return fetchAuthData('/api/v2/leaderboard/wallets/counts');
}

export async function getCuratedWalletList(
  sortBy: string = "total_pnl",
  sortOrder: string = "desc",
  limit: number = 50,
  offset: number = 0,
  search: string = "",
  category: string = "",
  filters: {
    filterCategory?: string;
    filterSubcategory?: string;
    minRoi?: number;
    maxRoi?: number;
    minPnl?: number;
    maxPnl?: number;
    minWins?: number;
    maxWins?: number;
    minWinRate?: number;
    maxWinRate?: number;
    window?: number;
  } = {},
) {
  let url = "";
  if (category && category !== "OVERALL") {
    // If a specific category tab is selected, use the new category-curated endpoint
    // to show wallets specifically curated for this category (or subcategory)
    let sBy = sortBy;
    if (sortBy === "total_pnl") sBy = "category_pnl";
    if (sortBy === "roi_pct") sBy = "category_roi";
    if (sortBy === "win_rate") sBy = "category_win_rate";
    if (sortBy === "total_volume") sBy = "category_volume";

    url = `/api/v2/leaderboard/category-curated?category=${encodeURIComponent(category)}&sort_by=${sBy}&sort_order=${sortOrder}&limit=${limit}&offset=${offset}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (filters.filterSubcategory) url += `&subcategory=${encodeURIComponent(filters.filterSubcategory)}`;
  } else {
    // Global curated list
    url = `/api/v2/leaderboard/curated-wallets?sort_by=${sortBy}&sort_order=${sortOrder}&limit=${limit}&offset=${offset}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (filters.filterCategory) url += `&filter_category=${encodeURIComponent(filters.filterCategory)}`;
    if (filters.filterSubcategory) url += `&filter_subcategory=${encodeURIComponent(filters.filterSubcategory)}`;
    if (filters.minRoi != null) url += `&min_roi=${filters.minRoi}`;
    if (filters.maxRoi != null) url += `&max_roi=${filters.maxRoi}`;
    if (filters.minPnl != null) url += `&min_pnl=${filters.minPnl}`;
    if (filters.maxPnl != null) url += `&max_pnl=${filters.maxPnl}`;
    if (filters.minWins != null) url += `&min_wins=${filters.minWins}`;
    if (filters.maxWins != null) url += `&max_wins=${filters.maxWins}`;
    if (filters.minWinRate != null) url += `&min_win_rate=${filters.minWinRate}`;
    if (filters.maxWinRate != null) url += `&max_win_rate=${filters.maxWinRate}`;
    if (filters.window != null) url += `&window=${filters.window}`;
  }
  return fetchAuthData(url);
}

export async function getSubcategories(category: string) {
  if (!category) return { subcategories: [] };
  return fetchAuthData(`/api/v2/leaderboard/subcategories?category=${encodeURIComponent(category)}`);
}

export async function fetchWhaleMetrics() {
  return fetchAuthData('/api/tracker/metrics');
}

export async function addCustomWallets(wallets: { address: string; reason?: string }[]) {
  return fetchAuthData('/api/v2/wallets/custom', {
    method: 'POST',
    body: JSON.stringify({ wallets })
  });
}

export async function getTrackerLists() {
  return fetchAuthData(`/api/tracker/lists`);
}

export async function createTrackerList(name: string) {
  return fetchAuthData(`/api/tracker/lists?name=${encodeURIComponent(name)}`, { method: "POST" });
}

export async function deleteTrackerList(listId: number) {
  return fetchAuthData(`/api/tracker/lists/${listId}`, { method: "DELETE" });
}

export async function getTrackerListWallets(listId: number) {
  return fetchAuthData(`/api/tracker/lists/${listId}/wallets`);
}

export async function addWalletToTrackerList(listId: number, walletAddress: string, note: string = "") {
  return fetchAuthData(`/api/tracker/lists/${listId}/wallets?wallet_address=${encodeURIComponent(walletAddress)}&note=${encodeURIComponent(note)}`, { method: "POST" });
}

export async function removeWalletFromTrackerList(listId: number, walletAddress: string) {
  return fetchAuthData(`/api/tracker/lists/${listId}/wallets/${walletAddress}`, { method: "DELETE" });
}



export async function getWatchlist() {
  return fetchAuthData(`/api/watchlist`);
}

export async function toggleWalletAlert(address: string, enabled: boolean) {
  return fetchAuthData(`/api/watchlist/${address}/alerts?enabled=${enabled}`, {
    method: 'POST'
  });
}


