"use client";

import { useEffect, useState, useCallback } from "react";
import { getCuratedWalletList, toggleWatchlist, getSubcategories } from "@/utils/api";
import { formatCurrency } from "@/utils/format";
import Link from "next/link";
import { Star, Search, Copy, PlusCircle, Check, Info, ChevronDown, ChevronUp, X, SlidersHorizontal } from "lucide-react";

interface CuratedWallet {
  address: string;
  username: string | null;
  source_type: string;
  is_dormant: boolean;
  last_trade_at: string | null;
  curated_at: string | null;
  track_count: number;
  last_checked_for_curated: string | null;
  total_pnl: number;
  win_rate: number;
  roi_pct: number;
  total_volume: number;
  resolved_count: number;
  winning_count: number;
  website_pnl: number;
  position_value: number;
  category: string | null;
  subcategory: string | null;
  active_category: string | null;
  tier: string | null;
  last_active: string | null;
}

const CATEGORIES = [
  "Politics", "Sports", "Esports", "Crypto", "Finance",
  "Culture", "Mentions", "Weather", "Economics", "Tech",
];

const CATEGORY_TABS = [
  { key: "OVERALL", label: "All" },
  { key: "SPORTS", label: "Sports" },
  { key: "POLITICS", label: "Politics" },
  { key: "CRYPTO", label: "Crypto" },
  { key: "ECONOMICS", label: "Economics" },
  { key: "TECH", label: "Tech" },
  { key: "FINANCE", label: "Finance" },
  { key: "CULTURE", label: "Culture" },
  { key: "ESPORTS", label: "Esports" },
  { key: "WEATHER", label: "Weather" },
];

const CATEGORY_TAB_COLORS: Record<string, string> = {
  OVERALL: "bg-foreground text-background",
  SPORTS: "bg-green-500/15 text-green-400 border border-green-500/20",
  POLITICS: "bg-blue-500/15 text-blue-400 border border-blue-500/20",
  CRYPTO: "bg-purple-500/15 text-purple-400 border border-purple-500/20",
  ECONOMICS: "bg-orange-500/15 text-orange-400 border border-orange-500/20",
  TECH: "bg-cyan-500/15 text-cyan-400 border border-cyan-500/20",
  FINANCE: "bg-yellow-500/15 text-yellow-400 border border-yellow-500/20",
  CULTURE: "bg-pink-500/15 text-pink-400 border border-pink-500/20",
  ESPORTS: "bg-red-500/15 text-red-400 border border-red-500/20",
  WEATHER: "bg-teal-500/15 text-teal-400 border border-teal-500/20",
};

const SORT_OPTIONS = [
  { value: "total_pnl", label: "PnL" },
  { value: "win_rate", label: "Win Rate" },
  { value: "roi_pct", label: "ROI" },
  { value: "total_volume", label: "Volume" },
  { value: "resolved_count", label: "Trades" },
  { value: "winning_count", label: "Wins" },
  { value: "pnl_100", label: "PnL 100" },
  { value: "pnl_300", label: "PnL 300" },
  { value: "pnl_800", label: "PnL 800" },
  { value: "pnl_1500", label: "PnL 1500" },
  { value: "pnl_2500", label: "PnL 2500" },
];

const PNL_WINDOW_OPTIONS = [
  { value: "", label: "All-Time" },
  { value: "pnl_100", label: "Last 100" },
  { value: "pnl_300", label: "Last 300" },
  { value: "pnl_800", label: "Last 800" },
  { value: "pnl_1500", label: "Last 1500" },
  { value: "pnl_2500", label: "Last 2500" },
];

function formatAddress(addr: string) {
  if (!addr) return "Unknown";
  if (addr.length < 10) return addr;
  return `${addr.slice(0, 5)}...${addr.slice(-4)}`;
}

export default function CuratedListPage() {
  const [wallets, setWallets] = useState<CuratedWallet[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("OVERALL");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("total_pnl");
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [watchlistStatus, setWatchlistStatus] = useState<Record<string, "idle" | "loading" | "success">>({});
  const [showFilters, setShowFilters] = useState(false);
  const pageSize = 50;

  // Filter state
  const [filterSubcategory, setFilterSubcategory] = useState("");
  
  const [minRoi, setMinRoi] = useState("");
  const [maxRoi, setMaxRoi] = useState("");
  const [minPnl, setMinPnl] = useState("");
  const [maxPnl, setMaxPnl] = useState("");
  const [minWinRate, setMinWinRate] = useState("");
  const [maxWinRate, setMaxWinRate] = useState("");
  
  const [pnlWindow, setPnlWindow] = useState("");
  const [subcategoryOptions, setSubcategoryOptions] = useState<string[]>([]);
  const [pendingFilters, setPendingFilters] = useState({
    minRoi: "", maxRoi: "", minPnl: "", maxPnl: "", minWinRate: "", maxWinRate: "", pnlWindow: ""
  });
  const [expandedAccordion, setExpandedAccordion] = useState<string | null>(null);


  const isCategoryView = category !== "OVERALL";

  // Fetch subcategories when category changes
  useEffect(() => {
    if (category === "OVERALL") {
      setSubcategoryOptions([]);
      setFilterSubcategory("");
      return;
    }
    getSubcategories(category).then((data) => {
      setSubcategoryOptions(data.subcategories || []);
      setFilterSubcategory("");
    }).catch(() => {
      setSubcategoryOptions([]);
      setFilterSubcategory("");
    });
  }, [category]);

  const activeFilterCount = [
    minRoi, maxRoi,
    minPnl, maxPnl,
    minWinRate, maxWinRate,
    pnlWindow,
  ].filter(Boolean).length;

  const clearFilters = () => {
    setFilterSubcategory("");
    setMinRoi(""); setMaxRoi("");
    setMinPnl(""); setMaxPnl("");
    setMinWinRate(""); setMaxWinRate("");
    setPnlWindow("");
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (page - 1) * pageSize;
      const windowNum = pnlWindow ? Number(pnlWindow.replace("pnl_", "")) : undefined;

      const data = await getCuratedWalletList(sortBy, pageSize, offset, search, category, {
        filterSubcategory: filterSubcategory || undefined,
        minRoi: minRoi ? Number(minRoi) : undefined,
        maxRoi: maxRoi ? Number(maxRoi) : undefined,
        minPnl: minPnl ? Number(minPnl) : undefined,
        maxPnl: maxPnl ? Number(maxPnl) : undefined,
        minWinRate: minWinRate ? Number(minWinRate) : undefined,
        maxWinRate: maxWinRate ? Number(maxWinRate) : undefined,
        window: windowNum,
      });
      setWallets(data.wallets || []);
      setTotal(data.total_count || 0);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [sortBy, page, search, category, filterSubcategory, minRoi, maxRoi, minPnl, maxPnl, minWinRate, maxWinRate, pnlWindow]);

  useEffect(() => { fetchData(); }, [fetchData]);

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

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const pnlWindowLabel = PNL_WINDOW_OPTIONS.find(o => o.value === pnlWindow)?.label || "All-Time";

  return (
    <div className="w-full h-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Star className="w-5 h-5 text-yellow-400 fill-yellow-400" />
            Curated Wallets
          </h1>
          <p className="text-xs text-muted-fg mt-0.5">
            {isCategoryView
              ? `${CATEGORY_TABS.find(c => c.key === category)?.label} wallets - category-specific PnL`
              : "ROI > 30% OR Win Rate > 60% OR PnL > $10k - active in last 30 days"
            }
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-yellow-400">{total.toLocaleString()}</div>
          <div className="text-[10px] text-muted-fg">{isCategoryView ? `${category} wallets` : "Curated"}</div>
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex items-center gap-4 flex-shrink-0 flex-wrap border-b border-border w-full pb-0">
        {CATEGORY_TABS.map((cat) => (
          <button
            key={cat.key}
            onClick={() => { setCategory(cat.key); setPage(1); setSortBy("total_pnl"); }}
            className={`px-1 py-2 text-[14px] font-medium transition-colors border-b-2 -mb-[1px] ${
              category === cat.key
                ? "text-blue-500 border-blue-500"
                : "text-muted-fg border-transparent hover:text-foreground"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Search + Sort + Filter toggle */}
      <div className="flex items-center justify-between flex-shrink-0 py-1">
        <div className="relative w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-fg" />
          <input
            type="text"
            placeholder="Filter wallets..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-surface border border-border text-sm focus:border-primary focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-3">

          {subcategoryOptions.length > 0 && (
            <select
              value={filterSubcategory}
              onChange={(e) => { setFilterSubcategory(e.target.value); setPage(1); }}
              className="px-3 py-2 rounded-lg bg-surface border border-border text-xs font-semibold text-muted-fg hover:text-foreground cursor-pointer transition-colors tracking-wider"
            >
              <option value="">All Subcategories</option>
              {subcategoryOptions.map((sub) => (
                <option key={sub} value={sub}>{sub}</option>
              ))}
            </select>
          )}
          <select
            value={sortBy}
            onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
            className="px-3 py-2 rounded-lg bg-surface border border-border text-xs font-semibold text-muted-fg hover:text-foreground cursor-pointer transition-colors uppercase tracking-wider"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>Sort: {opt.label}</option>
            ))}
          </select>
          <button
            onClick={() => {
              setPendingFilters({
                minRoi: minRoi,
                maxRoi: maxRoi,
                minPnl: minPnl,
                maxPnl: maxPnl,
                minWinRate: minWinRate,
                maxWinRate: maxWinRate,
                pnlWindow: pnlWindow,
              });
              setShowFilters(true);
            }}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-colors uppercase tracking-wider ${
              activeFilterCount > 0
                ? "bg-blue-500/10 text-blue-500 border border-blue-500/30"
                : "bg-surface text-muted-fg hover:text-foreground border border-border"
            }`}
          >
            <SlidersHorizontal size={14} />
            FILTERS
            {activeFilterCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded bg-blue-500 text-white text-[10px] font-bold">
                {activeFilterCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Filter Modal */}
      {showFilters && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl w-[500px] max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface-2/50">
              <div className="flex items-center gap-2">
                <SlidersHorizontal className="w-5 h-5 text-foreground" />
                <h2 className="text-lg font-bold text-foreground">Filters</h2>
              </div>
              <button 
                onClick={() => setShowFilters(false)}
                className="p-1.5 text-muted-fg hover:text-foreground hover:bg-surface-3 rounded-md transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              
              {/* Accordion Item: ROI */}
              <div className="border border-border rounded-lg overflow-hidden">
                <button 
                  onClick={() => setExpandedAccordion(expandedAccordion === 'roi' ? null : 'roi')}
                  className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface-2 transition-colors"
                >
                  <span className="text-sm font-semibold">ROI</span>
                  <div className="flex items-center gap-2">
                    {pendingFilters.minRoi || pendingFilters.maxRoi && <span className="px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-500 rounded">{pendingFilters.minRoi || pendingFilters.maxRoi ? 'Active' : ''}</span>}
                    {expandedAccordion === 'roi' ? <ChevronUp size={16} className="text-muted-fg" /> : <ChevronDown size={16} className="text-muted-fg" />}
                  </div>
                </button>
                {expandedAccordion === 'roi' && (
                                    <div className="px-4 pb-4 bg-surface border-t border-border/50">
                    <div className="flex items-center gap-3 mt-3">
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">From (%)</label>
                        <input 
                          type="number" 
                          placeholder="Min"
                          value={pendingFilters.minRoi}
                          onChange={(e) => setPendingFilters({...pendingFilters, minRoi: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">To (%)</label>
                        <input 
                          type="number" 
                          placeholder="Max"
                          value={pendingFilters.maxRoi}
                          onChange={(e) => setPendingFilters({...pendingFilters, maxRoi: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>


              {/* Accordion Item: PnL */}
              <div className="border border-border rounded-lg overflow-hidden">
                <button 
                  onClick={() => setExpandedAccordion(expandedAccordion === 'pnl' ? null : 'pnl')}
                  className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface-2 transition-colors"
                >
                  <span className="text-sm font-semibold">PnL</span>
                  <div className="flex items-center gap-2">
                    {pendingFilters.minPnl || pendingFilters.maxPnl && <span className="px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-500 rounded">{pendingFilters.minPnl || pendingFilters.maxPnl ? 'Active' : ''}</span>}
                    {expandedAccordion === 'pnl' ? <ChevronUp size={16} className="text-muted-fg" /> : <ChevronDown size={16} className="text-muted-fg" />}
                  </div>
                </button>
                {expandedAccordion === 'pnl' && (
                                    <div className="px-4 pb-4 bg-surface border-t border-border/50">
                    <div className="flex items-center gap-3 mt-3">
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">From ($)</label>
                        <input 
                          type="number" 
                          placeholder="Min"
                          value={pendingFilters.minPnl}
                          onChange={(e) => setPendingFilters({...pendingFilters, minPnl: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">To ($)</label>
                        <input 
                          type="number" 
                          placeholder="Max"
                          value={pendingFilters.maxPnl}
                          onChange={(e) => setPendingFilters({...pendingFilters, maxPnl: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>


              {/* Accordion Item: Win Rate */}
              <div className="border border-border rounded-lg overflow-hidden">
                <button 
                  onClick={() => setExpandedAccordion(expandedAccordion === 'winRate' ? null : 'winRate')}
                  className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface-2 transition-colors"
                >
                  <span className="text-sm font-semibold">Win Rate</span>
                  <div className="flex items-center gap-2">
                    {pendingFilters.minWinRate || pendingFilters.maxWinRate && <span className="px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-500 rounded">{pendingFilters.minWinRate || pendingFilters.maxWinRate ? 'Active' : ''}</span>}
                    {expandedAccordion === 'winRate' ? <ChevronUp size={16} className="text-muted-fg" /> : <ChevronDown size={16} className="text-muted-fg" />}
                  </div>
                </button>
                {expandedAccordion === 'winRate' && (
                                    <div className="px-4 pb-4 bg-surface border-t border-border/50">
                    <div className="flex items-center gap-3 mt-3">
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">From (0-1)</label>
                        <input 
                          type="number" 
                          step="0.01"
                          placeholder="Min"
                          value={pendingFilters.minWinRate}
                          onChange={(e) => setPendingFilters({...pendingFilters, minWinRate: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="text-xs text-muted-fg mb-1 block">To (0-1)</label>
                        <input 
                          type="number" 
                          step="0.01"
                          placeholder="Max"
                          value={pendingFilters.maxWinRate}
                          onChange={(e) => setPendingFilters({...pendingFilters, maxWinRate: e.target.value})}
                          className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>


              {/* Accordion Item: PnL Window */}
              <div className="border border-border rounded-lg overflow-hidden">
                <button 
                  onClick={() => setExpandedAccordion(expandedAccordion === 'pnlWindow' ? null : 'pnlWindow')}
                  className="w-full flex items-center justify-between px-4 py-3 bg-surface hover:bg-surface-2 transition-colors"
                >
                  <span className="text-sm font-semibold">PnL Window</span>
                  <div className="flex items-center gap-2">
                    {pendingFilters.pnlWindow && <span className="px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-500 rounded">{PNL_WINDOW_OPTIONS.find(o => o.value === pendingFilters.pnlWindow)?.label || ''}</span>}
                    {expandedAccordion === 'pnlWindow' ? <ChevronUp size={16} className="text-muted-fg" /> : <ChevronDown size={16} className="text-muted-fg" />}
                  </div>
                </button>
                {expandedAccordion === 'pnlWindow' && (
                  <div className="px-4 pb-3 bg-surface border-t border-border/50">
                    <select
                      value={pendingFilters.pnlWindow}
                      onChange={(e) => setPendingFilters({...pendingFilters, pnlWindow: e.target.value})}
                      className="w-full mt-3 px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm focus:border-primary outline-none"
                    >
                      {PNL_WINDOW_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                    </select>
                  </div>
                )}
              </div>

            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-border flex items-center justify-between bg-surface-2/30">
              <button 
                onClick={() => setPendingFilters({minRoi: "", maxRoi: "", minPnl: "", maxPnl: "", minWinRate: "", maxWinRate: "", pnlWindow: ""})}
                className="text-red-500 hover:text-red-400 text-sm font-medium px-4 py-2 border border-red-500/30 hover:bg-red-500/10 rounded-lg transition-colors"
              >
                Reset All Filters
              </button>
              
              <button 
                onClick={() => {
                  setMinRoi(pendingFilters.minRoi);
                  setMaxRoi(pendingFilters.maxRoi);
                  setMinPnl(pendingFilters.minPnl);
                  setMaxPnl(pendingFilters.maxPnl);
                  setMinWinRate(pendingFilters.minWinRate);
                  setMaxWinRate(pendingFilters.maxWinRate);
                  setPage(1);
                  setShowFilters(false);
                }}
                className="bg-blue-500 hover:bg-blue-600 text-white text-sm font-bold px-8 py-2 rounded-lg transition-colors shadow-lg shadow-blue-500/20"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Table */}      {/* Table */}
      <div className="flex-1 overflow-auto bg-surface rounded-xl border border-border">
        {loading ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm">Loading...</div>
        ) : wallets.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm">
            {isCategoryView ? `No ${category} wallets found` : "No curated wallets found"}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-surface text-muted-fg font-mono uppercase tracking-wider text-xs">
                <th className="py-2.5 px-4 font-semibold w-12 text-center">#</th>
                <th className="py-2.5 px-4 font-semibold">Wallet</th>
                {!isCategoryView && <th className="py-2.5 px-4 font-semibold">Category</th>}
                <th className="py-2.5 px-4 font-semibold text-right">Win%</th>
                <th className="py-2.5 px-4 font-semibold text-right">Wins</th>
                <th className="py-2.5 px-4 font-semibold text-right">
                  {pnlWindow ? pnlWindowLabel : "PnL"}
                </th>
                <th className="py-2.5 px-4 font-semibold text-right">ROI</th>
                <th className="py-2.5 px-4 font-semibold text-right">Volume</th>
                <th className="py-2.5 px-4 font-semibold text-right">Trades</th>
                <th className="py-2.5 px-4 font-semibold text-right">Last Active</th>
                <th className="py-2.5 px-4 font-semibold">Curated</th>
              </tr>
            </thead>
            <tbody>
              {wallets.map((w, i) => {
                const pnl = Number(w.total_pnl || 0);
                const roi = Number(w.roi_pct || 0);
                return (
                  <tr key={w.address} className="border-b border-border hover:bg-background/50 transition-colors">
                    <td className="py-2.5 px-4 text-center font-medium text-muted-fg">{(page - 1) * pageSize + i + 1}</td>
                    <td className="py-2.5 px-4 font-medium text-foreground">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Star className="w-3 h-3 text-yellow-400 fill-yellow-400 flex-shrink-0" />
                        {w.username && w.username.length <= 20 && (
                          <span className="text-muted-fg text-xs font-semibold truncate max-w-[100px]" title={w.username}>{w.username}</span>
                        )}
                        <Link
                          href={`/wallet/${w.address}`}
                          className="hover:text-primary transition-colors font-mono bg-primary/5 px-2 py-0.5 rounded border border-primary/10 whitespace-nowrap flex-shrink-0"
                        >
                          {formatAddress(w.address)}
                        </Link>
                        <button onClick={(e) => handleCopy(e, w.address)} className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors" title="Copy Address">
                          {copiedAddress === w.address ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                        </button>
                        <a href={`https://activity.polymarket-tools.com/?address=${w.address}`} target="_blank" rel="noopener noreferrer" className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors" title="PolyTools">
                          <Info size={12} />
                        </a>
                        <a href={`https://polymarket.com/profile/${w.address}`} target="_blank" rel="noopener noreferrer" className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-blue-400 transition-colors" title="Polymarket">
                          <svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12">
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-6h2v6zm0-8h-2V7h2v2zm3 8h-2v-6h2v6zm0-8h-2V7h2v2zm3 8h-2v-6h2v6zm0-8h-2V7h2v2z" />
                          </svg>
                        </a>
                        <button onClick={(e) => handleAddToWatchlist(e, w.address)} disabled={watchlistStatus[w.address] === "loading" || watchlistStatus[w.address] === "success"} className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors disabled:opacity-50" title="Add to Watchlist">
                          {watchlistStatus[w.address] === "success" ? <Check size={12} className="text-green-500" /> : <PlusCircle size={12} />}
                        </button>
                      </div>
                    </td>
                    {!isCategoryView && (
                      <td className="py-2.5 px-4 text-xs">
                        {w.category || "\u2014"}
                        {w.subcategory && <div className="text-muted-fg text-[10px]">{w.subcategory}</div>}
                      </td>
                    )}
                    <td className="py-2.5 px-4 text-right font-mono">{(Number(w.win_rate || 0) * 100).toFixed(0)}%</td>
                    <td className="py-2.5 px-4 text-right font-mono">{w.winning_count || 0}</td>
                    <td className={`py-2.5 px-4 text-right font-mono font-bold ${pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                      {pnl > 0 ? "+" : ""}{formatCurrency(pnl)}
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono">
                      <span className={roi >= 0 ? "text-green-500" : "text-red-500"}>
                        {roi > 0 ? "+" : ""}{roi.toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(Number(w.total_volume || 0))}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{w.resolved_count || 0}</td>
                    <td className="py-2.5 px-4 text-right font-mono text-muted-fg text-xs">{w.last_active ? new Date(w.last_active).toLocaleDateString() : "—"}</td>
                    <td className="py-2.5 px-4 text-xs text-muted-fg">
                      {w.curated_at ? new Date(w.curated_at).toLocaleDateString() : "\u2014"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      <div className="flex justify-end items-center py-2 px-2 flex-shrink-0">
        <div className="flex items-center space-x-1">
          <button onClick={() => setPage(1)} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">First</button>
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&lt;</button>
          <span className="text-xs text-muted-fg mx-1">Page {page} / {totalPages}</span>
          <button onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&gt;</button>
          <button onClick={() => setPage(totalPages)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">Last</button>
        </div>
      </div>
    </div>
  );
}
