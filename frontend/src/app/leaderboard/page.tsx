"use client";

import { useEffect, useState, useCallback } from "react";
import { getGlobalLeaderboard, getCuratedLeaderboard, toggleWatchlist } from "@/utils/api";
import { formatCurrency } from "@/utils/format";
import Link from "next/link";
import { Medal, Copy, PlusCircle, Check, Globe, Filter, Info } from "lucide-react";

interface LeaderboardEntry {
  address: string;
  win_rate: number | null;
  roi_pct: number | null;
  resolved_count: number;
  winning_count?: number;
  total_volume: string;
  tier: string;
  strategy: string | null;
  active_days: number;
  alpha_score: number | null;
  total_pnl?: string;
  realized_pnl?: string;
  unrealized_pnl?: string;
  position_value?: string;
  added_reason?: string;
  added_at?: string;
  biggest_win?: string;
  biggest_loss?: string;
  max_trade_size?: string;
  website_pnl?: number | null;
  website_volume?: number | null;
  website_rank?: number | null;
  username?: string;
}

const TIER_COLORS: Record<string, string> = {
  Diamond: "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20",
  Platinum: "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20",
  Gold: "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20",
  Silver: "bg-slate-500/10 text-slate-400 border border-slate-500/20",
  Bronze: "bg-orange-500/10 text-orange-400 border border-orange-500/20",
};

function formatAddress(addr: string) {
  if (!addr) return "Unknown";
  if (addr.length < 10) return addr;
  return `${addr.slice(0, 5)}...${addr.slice(-4)}`;
}

export default function LeaderboardPage() {
  const [section, setSection] = useState<"global" | "curated">("global");

  return (
    <div className="w-full h-full flex flex-col bg-background">
      <div className="flex-shrink-0 mb-4">
        <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mb-3">
          Leaderboard
        </h1>
        <div className="flex bg-surface-2 border border-border p-0.5 rounded-lg w-fit">
          <button
            onClick={() => setSection("global")}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
              section === "global"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            <Globe size={13} /> All Discovered Wallets
          </button>
          <button
            onClick={() => setSection("curated")}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${
              section === "curated"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            <Filter size={13} /> Curated
          </button>
        </div>
      </div>

      {section === "global" ? <GlobalSection /> : <CuratedSection />}
    </div>
  );
}

// ─── Shared table component ──────────────────────────────────────────────

function LeaderboardTable({
  data,
  loading,
  columns,
  page,
  setPage,
  sortField,
  setSortField,
  totalCount,
  pageSize,
  searchQuery,
}: {
  data: LeaderboardEntry[];
  loading: boolean;
  columns: { key: string; label: string; field: string }[];
  page: number;
  setPage: (fn: (p: number) => number) => void;
  sortField: string;
  setSortField: (f: string) => void;
  totalCount: number;
  pageSize: number;
  searchQuery: string;
}) {
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [watchlistStatus, setWatchlistStatus] = useState<Record<string, "idle" | "loading" | "success">>({});

  const handleCopy = (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  const handleAddToWatchlist = async (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    try {
      setWatchlistStatus((prev) => ({ ...prev, [address]: "loading" }));
      await toggleWatchlist(address, "add");
      setWatchlistStatus((prev) => ({ ...prev, [address]: "success" }));
      setTimeout(() => setWatchlistStatus((prev) => ({ ...prev, [address]: "idle" })), 3000);
    } catch {
      setWatchlistStatus((prev) => ({ ...prev, [address]: "idle" }));
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  const renderCellValue = (entry: LeaderboardEntry, field: string) => {
    switch (field) {
      case "win_rate":
        return `${((parseFloat(String(entry.win_rate || 0)) * 100)).toFixed(1)}%`;
      case "roi_pct": {
        const v = parseFloat(String(entry.roi_pct || 0));
        return (
          <span className={v >= 0 ? "text-green-500" : "text-red-500"}>
            {v > 0 ? "+" : ""}{v.toFixed(2)}%
          </span>
        );
      }
      case "total_pnl": {
        const v = parseFloat(entry.total_pnl || "0");
        return (
          <span className={v >= 0 ? "text-green-500 font-bold" : "text-red-500 font-bold"}>
            {v > 0 ? "+" : ""}{formatCurrency(v)}
          </span>
        );
      }
      case "realized_pnl": {
        const v = parseFloat(entry.realized_pnl || "0");
        return (
          <span className={v >= 0 ? "text-green-500/90" : "text-red-500/90"}>
            {v > 0 ? "+" : ""}{formatCurrency(v)}
          </span>
        );
      }
      case "unrealized_pnl": {
        const v = parseFloat(entry.unrealized_pnl || "0");
        return (
          <span className={v >= 0 ? "text-green-500/90" : "text-red-500/90"}>
            {v > 0 ? "+" : ""}{formatCurrency(v)}
          </span>
        );
      }
      case "total_volume":
        return formatCurrency(parseFloat(entry.total_volume || "0"));
      case "position_value":
        return formatCurrency(parseFloat(entry.position_value || "0"));
      case "website_pnl": {
        const v = entry.website_pnl;
        if (v == null) return "—";
        return (
          <span className={v >= 0 ? "text-green-500 font-bold" : "text-red-500 font-bold"}>
            {v > 0 ? "+" : ""}{formatCurrency(v)}
          </span>
        );
      }
      case "max_trade_size":
        return formatCurrency(parseFloat(entry.max_trade_size || "0"));
      case "resolved_count":
        return entry.resolved_count || 0;
      case "alpha_score":
        return parseFloat(String(entry.alpha_score || 0)).toFixed(1);
      case "tier":
        return (
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${TIER_COLORS[entry.tier] || "bg-surface-2 text-muted-fg"}`}>
            {entry.tier || "—"}
          </span>
        );
      case "active_days":
        return entry.active_days || 0;
      case "website_rank":
        return entry.website_rank ? `#${entry.website_rank.toLocaleString()}` : "—";
      case "username": {
        const name = entry.username || "";
        if (!name || name.length > 20) return "—";
        return <span title={name}>{name}</span>;
      }
      default:
        return String((entry as unknown as Record<string, unknown>)[field] ?? "—");
    }
  };

  return (
    <>
      {/* Table */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden flex-1 min-h-0 flex flex-col shadow-sm">
        <div className="overflow-x-auto overflow-y-auto flex-1">
          <table className="w-full text-left text-sm border-collapse min-w-[900px]">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-surface text-muted-fg font-mono uppercase tracking-wider text-xs">
                <th className="py-2.5 px-4 font-semibold w-16 text-center">Rank</th>
                <th className="py-2.5 px-4 font-semibold">User</th>
                {columns.map((h) => (
                  <th
                    key={h.key}
                    className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground transition-colors select-none"
                    onClick={() => { setSortField(h.field); setPage(() => 1); }}
                  >
                    {h.label} {sortField === h.field && "↓"}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={2 + columns.length} className="py-12 text-center text-muted-fg">
                    Loading...
                  </td>
                </tr>
              ) : data.length === 0 ? (
                <tr>
                  <td colSpan={2 + columns.length} className="py-12 text-center text-muted-fg">
                    No wallets found.
                  </td>
                </tr>
              ) : (
                data
                  .filter((entry) => !searchQuery || entry.address.toLowerCase().includes(searchQuery.toLowerCase()))
                  .map((entry, index) => (
                    <tr key={entry.address} className="border-b border-border hover:bg-background/50 transition-colors">
                      <td className="py-2.5 px-4 text-center font-medium text-muted-fg">
                        {index < 3 && page === 1 ? (
                          <Medal
                            className={`inline-block w-5 h-5 ${
                              index === 0 ? "text-yellow-500" : index === 1 ? "text-slate-400" : "text-amber-600"
                            }`}
                          />
                        ) : (
                          (page - 1) * pageSize + index + 1
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-medium text-foreground">
                        <div className="flex items-center gap-2 min-w-0">
                          {entry.username && entry.username.length <= 20 && (
                            <span className="text-muted-fg text-xs font-semibold truncate max-w-[120px]" title={entry.username}>{entry.username}</span>
                          )}
                          <Link
                            href={`/wallet/${entry.address}`}
                            className="hover:text-primary transition-colors font-mono bg-primary/5 px-2 py-0.5 rounded border border-primary/10 whitespace-nowrap flex-shrink-0"
                          >
                            {formatAddress(entry.address)}
                          </Link>
                          <button
                            onClick={(e) => handleCopy(e, entry.address)}
                            className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors"
                            title="Copy Address"
                          >
                            {copiedAddress === entry.address ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                          </button>
                          <a
                            href={`https://activity.polymarket-tools.com/?address=${entry.address}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors"
                            title="View on PolyTools"
                          >
                            <Info size={14} />
                          </a>
                          <a
                            href={`https://polymarket.com/profile/${entry.address}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-blue-400 transition-colors"
                            title="View on Polymarket"
                          >
                            <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-6h2v6zm0-8h-2V7h2v2zm3 8h-2v-6h2v6zm0-8h-2V7h2v2zm3 8h-2v-6h2v6zm0-8h-2V7h2v2z" />
                            </svg>
                          </a>
                          <button
                            onClick={(e) => handleAddToWatchlist(e, entry.address)}
                            disabled={watchlistStatus[entry.address] === "loading" || watchlistStatus[entry.address] === "success"}
                            className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors disabled:opacity-50"
                            title="Add to Watchlist"
                          >
                            {watchlistStatus[entry.address] === "success" ? <Check size={14} className="text-green-500" /> : <PlusCircle size={14} />}
                          </button>
                        </div>
                      </td>
                      {columns.map((h) => (
                        <td key={h.key} className="py-2.5 px-4 text-right font-mono font-medium whitespace-nowrap">
                          {renderCellValue(entry, h.field)}
                        </td>
                      ))}
                    </tr>
                  ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex justify-end items-center py-4 px-2">
        <div className="flex items-center space-x-1">
          <button onClick={() => setPage(() => 1)} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">First</button>
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&lt;</button>
          <span className="text-xs text-muted-fg mx-1">Page {page} / {totalPages}</span>
          <button onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&gt;</button>
          <button onClick={() => setPage(() => totalPages)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">Last</button>
        </div>
      </div>
    </>
  );
}

// ─── Global Section: all discovered wallets ──────────────────────────────

function GlobalSection() {
  const [data, setData] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortField, setSortField] = useState("total_pnl");
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");

  const pageSize = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getGlobalLeaderboard(sortField, pageSize, (page - 1) * pageSize, searchQuery);
      setData(res.wallets || []);
      setTotalCount(res.total_count || 0);
    } catch (e) {
      console.error("Failed to fetch global leaderboard", e);
    } finally {
      setLoading(false);
    }
  }, [sortField, page, searchQuery]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { key: "username", label: "Username", field: "username" },
    { key: "website_pnl", label: "PnL (Polymarket)", field: "website_pnl" },
    { key: "website_rank", label: "Rank", field: "website_rank" },
    { key: "volume", label: "Volume", field: "total_volume" },
    { key: "win_rate", label: "Win Rate", field: "win_rate" },
    { key: "roi", label: "ROI", field: "roi_pct" },
    { key: "pnl", label: "PnL (System)", field: "total_pnl" },
    { key: "tier", label: "Tier", field: "tier" },
    { key: "resolved", label: "Resolved", field: "resolved_count" },
  ];

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Filters */}
      <div className="flex items-center gap-3 mb-3 flex-shrink-0 flex-wrap">
        <input
          type="text"
          placeholder="Search address..."
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
          className="bg-surface border border-border rounded-lg px-3 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder-muted-fg w-48 font-mono"
        />
        <div className="ml-auto text-xs text-muted-fg">
          {totalCount.toLocaleString()} wallets discovered
        </div>
      </div>

      <LeaderboardTable
        data={data}
        loading={loading}
        columns={columns}
        page={page}
        setPage={setPage}
        sortField={sortField}
        setSortField={(f) => { setSortField(f); setPage(1); }}
        totalCount={totalCount}
        pageSize={pageSize}
        searchQuery={searchQuery}
      />
    </div>
  );
}

// ─── Curated Section: filtered subset with conditions ────────────────────

function CuratedSection() {
  const [data, setData] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortField, setSortField] = useState("total_pnl");
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");

  const [tier, setTier] = useState("");
  const [minWinRate, setMinWinRate] = useState<number | null>(null);
  const [minRoi, setMinRoi] = useState<number | null>(null);
  const [minVolume, setMinVolume] = useState<number | null>(null);
  const [minResolved, setMinResolved] = useState<number | null>(null);
  const [minRealizedPnl, setMinRealizedPnl] = useState<number | null>(null);
  const [minActiveDays, setMinActiveDays] = useState<number | null>(null);

  const pageSize = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getCuratedLeaderboard(sortField, pageSize, (page - 1) * pageSize, {
        tier: tier || undefined,
        min_win_rate: minWinRate ?? undefined,
        min_roi: minRoi ?? undefined,
        min_volume: minVolume ?? undefined,
        min_resolved: minResolved ?? undefined,
        min_realized_pnl: minRealizedPnl ?? undefined,
        min_active_days: minActiveDays ?? undefined,
        search: searchQuery || undefined,
      });
      setData(res.wallets || []);
      setTotalCount(res.total_count || 0);
    } catch (e) {
      console.error("Failed to fetch curated leaderboard", e);
    } finally {
      setLoading(false);
    }
  }, [sortField, page, searchQuery, tier, minWinRate, minRoi, minVolume, minResolved, minRealizedPnl, minActiveDays]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const columns = [
    { key: "volume", label: "Volume", field: "total_volume" },
    { key: "win_rate", label: "Win Rate", field: "win_rate" },
    { key: "roi", label: "ROI", field: "roi_pct" },
    { key: "pnl", label: "PnL", field: "total_pnl" },
    { key: "realized", label: "Realized", field: "realized_pnl" },
    { key: "tier", label: "Tier", field: "tier" },
    { key: "resolved", label: "Resolved", field: "resolved_count" },
    { key: "active", label: "Active Days", field: "active_days" },
  ];

  const resetFilters = () => {
    setTier("");
    setMinWinRate(null);
    setMinRoi(null);
    setMinVolume(null);
    setMinResolved(null);
    setMinRealizedPnl(null);
    setMinActiveDays(null);
    setSearchQuery("");
    setPage(1);
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Filters */}
      <div className="flex items-center gap-3 mb-3 flex-shrink-0 flex-wrap">
        <select className="bg-surface border border-border rounded-md px-2 py-1 text-xs outline-none focus:border-primary text-foreground" value={tier} onChange={(e) => { setTier(e.target.value); setPage(1); }}>
          <option value="">All Tiers</option>
          <option value="Diamond">Diamond</option>
          <option value="Platinum">Platinum</option>
          <option value="Gold">Gold</option>
          <option value="Silver">Silver</option>
          <option value="Bronze">Bronze</option>
        </select>

        <select className="bg-surface border border-border rounded-md px-2 py-1 text-xs outline-none focus:border-primary text-foreground" value={minWinRate ?? ""} onChange={(e) => { setMinWinRate(e.target.value ? Number(e.target.value) : null); setPage(1); }}>
          <option value="">Any Win Rate</option>
          <option value="0.5">50%+</option>
          <option value="0.6">60%+</option>
          <option value="0.7">70%+</option>
          <option value="0.8">80%+</option>
        </select>

        <select className="bg-surface border border-border rounded-md px-2 py-1 text-xs outline-none focus:border-primary text-foreground" value={minVolume ?? ""} onChange={(e) => { setMinVolume(e.target.value ? Number(e.target.value) : null); setPage(1); }}>
          <option value="">Any Volume</option>
          <option value="10000">{`> $10k`}</option>
          <option value="100000">{`> $100k`}</option>
          <option value="1000000">{`> $1M`}</option>
        </select>

        <select className="bg-surface border border-border rounded-md px-2 py-1 text-xs outline-none focus:border-primary text-foreground" value={minResolved ?? ""} onChange={(e) => { setMinResolved(e.target.value ? Number(e.target.value) : null); setPage(1); }}>
          <option value="">Any Resolved</option>
          <option value="10">10+</option>
          <option value="50">50+</option>
          <option value="100">100+</option>
        </select>

        <input
          type="text"
          placeholder="Search address..."
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
          className="bg-surface border border-border rounded-lg px-3 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder-muted-fg w-40 font-mono"
        />

        <button onClick={resetFilters} className="text-xs text-muted-fg hover:text-foreground transition-colors underline">
          Reset
        </button>

        <div className="ml-auto text-xs text-muted-fg">
          {totalCount.toLocaleString()} curated wallets
        </div>
      </div>

      <LeaderboardTable
        data={data}
        loading={loading}
        columns={columns}
        page={page}
        setPage={setPage}
        sortField={sortField}
        setSortField={(f) => { setSortField(f); setPage(1); }}
        totalCount={totalCount}
        pageSize={pageSize}
        searchQuery={searchQuery}
      />
    </div>
  );
}
