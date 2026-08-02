"use client";

import { useEffect, useState, useCallback } from "react";
import { getCuratedWalletList, getSubcategories } from "@/utils/api";
import { formatCurrency, formatAddress } from "@/utils/format";
import { useCopyAddress } from "@/hooks/useCopyAddress";
import { useWatchlistAdd } from "@/hooks/useWatchlistAdd";
import { Pagination } from "@/components/wallets/Pagination";
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
  categories: string[];
  subcategories: string[];
  active_category: string | null;
  last_active: string | null;
  avg_buy_price: number;
  buys_below_10c: number;
  buys_below_20c: number;
  buys_below_30c: number;
  buys_below_40c: number;
  buys_above_70c: number;
  wins_below_10c: number;
  wins_below_20c: number;
  wins_below_30c: number;
  wins_below_40c: number;
  wins_above_70c: number;
  losses_below_10c: number;
  losses_below_20c: number;
  losses_below_30c: number;
  losses_below_40c: number;
  losses_above_70c: number;
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
  { key: "MENTIONS", label: "Mentions" },
  { key: "OTHER", label: "Others" },
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
  MENTIONS: "bg-indigo-500/15 text-indigo-400 border border-indigo-500/20",
  OTHER: "bg-gray-500/15 text-gray-400 border border-gray-500/20",
};

const SORT_OPTIONS = [
  { value: "total_pnl", label: "PnL" },
  { value: "win_rate", label: "Win Rate" },
  { value: "roi_pct", label: "ROI" },
  { value: "total_volume", label: "Volume" },
  { value: "resolved_count", label: "Resolved" },
  { value: "winning_count", label: "Wins" },
  { value: "pnl_100", label: "PnL 100" },
  { value: "pnl_300", label: "PnL 300" },
  { value: "pnl_800", label: "PnL 800" },
  { value: "pnl_1500", label: "PnL 1500" },
  { value: "pnl_2500", label: "PnL 2500" },
];

const PNL_WINDOW_OPTIONS = [
  { value: "", label: "Last 5000" },
  { value: "pnl_2500", label: "Last 2500" },
  { value: "pnl_1500", label: "Last 1500" },
  { value: "pnl_800", label: "Last 800" },
  { value: "pnl_300", label: "Last 300" },
  { value: "pnl_100", label: "Last 100" },
];

export default function CuratedListPage() {
  const [wallets, setWallets] = useState<CuratedWallet[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("OVERALL");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("total_pnl");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [tradeSortKey, setTradeSortKey] = useState<string | null>(null);
  const [tradeSortDir, setTradeSortDir] = useState<"desc" | "asc">("desc");

  const TRADE_SORT_CYCLE: Record<string, [string, "desc" | "asc"][]> = {
    buys_below_10c: [["buys_below_10c", "desc"], ["wins_below_10c", "desc"], ["wins_below_10c", "asc"], ["buys_below_10c", "asc"]],
    buys_below_20c: [["buys_below_20c", "desc"], ["wins_below_20c", "desc"], ["wins_below_20c", "asc"], ["buys_below_20c", "asc"]],
    buys_below_30c: [["buys_below_30c", "desc"], ["wins_below_30c", "desc"], ["wins_below_30c", "asc"], ["buys_below_30c", "asc"]],
    buys_below_40c: [["buys_below_40c", "desc"], ["wins_below_40c", "desc"], ["wins_below_40c", "asc"], ["buys_below_40c", "asc"]],
    buys_above_70c: [["buys_above_70c", "desc"], ["wins_above_70c", "desc"], ["wins_above_70c", "asc"], ["buys_above_70c", "asc"]],
  };

  const handleTradeSort = (key: string) => {
    const cycle = TRADE_SORT_CYCLE[key];
    if (!cycle) return;
    const currentIdx = cycle.findIndex(([k, d]) => k === tradeSortKey && d === tradeSortDir);
    const nextIdx = (currentIdx + 1) % cycle.length;
    const [nextKey, nextDir] = cycle[nextIdx];
    setTradeSortKey(nextKey);
    setTradeSortDir(nextDir);
    setPage(1);
  };

  const handleSort = (field: string) => {
    setTradeSortKey(null);
    if (sortBy === field) {
      setSortOrder(sortOrder === "desc" ? "asc" : "desc");
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
    setPage(1);
  };
  const { copiedAddress, handleCopy } = useCopyAddress();
  const { watchlistStatus, handleAddToWatchlist } = useWatchlistAdd();
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

      const data = await getCuratedWalletList(sortBy, sortOrder, pageSize, offset, search, category, {
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
  }, [sortBy, sortOrder, page, search, category, filterSubcategory, minRoi, maxRoi, minPnl, maxPnl, minWinRate, maxWinRate, pnlWindow]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const displayWallets = tradeSortKey
    ? [...wallets].sort((a, b) => {
        const fieldA = Number((a as unknown as Record<string, number>)[tradeSortKey] || 0);
        const fieldB = Number((b as unknown as Record<string, number>)[tradeSortKey] || 0);
        return tradeSortDir === "desc" ? fieldB - fieldA : fieldA - fieldB;
      })
    : wallets;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const pnlWindowLabel = PNL_WINDOW_OPTIONS.find(o => o.value === pnlWindow)?.label || "Last 5000";

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
              : "ROI > 30% OR PnL > $10k - active in last 30 days"
            }
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-yellow-400">{total.toLocaleString()}</div>
          <div className="text-[10px] text-muted-fg">{isCategoryView ? `${category} wallets` : "Curated"}</div>
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex flex-col gap-3 flex-shrink-0 border-b border-border w-full pb-3">
        <div className="flex items-center gap-4 flex-wrap">
          {CATEGORY_TABS.map((cat) => (
            <button
              key={cat.key}
              onClick={() => { setCategory(cat.key); setPage(1); setSortBy("total_pnl"); }}
              className={`px-1 py-1 text-[14px] font-medium transition-colors border-b-2 -mb-[1px] ${
                category === cat.key
                  ? "text-blue-500 border-blue-500"
                  : "text-muted-fg border-transparent hover:text-foreground"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {PNL_WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { 
                setPnlWindow(opt.value);
                setPendingFilters(prev => ({...prev, pnlWindow: opt.value}));
                setPage(1); 
              }}
              className={`px-3 py-1 text-[11px] font-semibold transition-colors rounded-full uppercase tracking-wider ${
                pnlWindow === opt.value
                  ? "bg-blue-500/10 text-blue-500 border border-blue-500/20"
                  : "text-muted-fg bg-surface-2 hover:bg-surface-3 border border-transparent"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Search + Subcategory Pills + Filter toggle */}
      <div className="flex items-center justify-between flex-shrink-0 py-1 gap-4">
        
        <div className="flex items-center gap-4 flex-1 overflow-hidden min-w-0">
          <div className="relative w-72 flex-shrink-0">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-fg" />
            <input
              type="text"
              placeholder="Filter wallets..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-surface border border-border text-sm focus:border-primary focus:outline-none"
            />
          </div>

          {/* Subcategory Pills */}
          {subcategoryOptions.length > 0 && (
            <div className="flex items-center gap-2 overflow-x-auto pb-1 flex-1 min-w-0 scrollbar-hide">
              <button
                onClick={() => { setFilterSubcategory(""); setPage(1); }}
                className={`px-3 py-1 text-xs font-semibold rounded-full whitespace-nowrap transition-colors border ${
                  filterSubcategory === ""
                    ? "bg-foreground text-background border-foreground"
                    : "bg-surface-2 text-muted-fg border-transparent hover:text-foreground hover:bg-surface-3"
                }`}
              >
                All
              </button>
              {subcategoryOptions.map((sub) => (
                <button
                  key={sub}
                  onClick={() => { setFilterSubcategory(sub); setPage(1); }}
                  className={`px-3 py-1 text-xs font-semibold rounded-full whitespace-nowrap transition-colors border ${
                    filterSubcategory === sub
                      ? "bg-foreground text-background border-foreground"
                      : "bg-surface-2 text-muted-fg border-transparent hover:text-foreground hover:bg-surface-3"
                  }`}
                >
                  {sub}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
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

      {/* Table */}
      <div className="flex-1 overflow-auto bg-surface rounded-xl border border-border">
        {loading ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm">Loading...</div>
        ) : wallets.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm">
            {isCategoryView ? `No ${category} wallets found` : "No curated wallets found"}
          </div>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[1100px]">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-surface text-muted-fg font-mono uppercase tracking-wider text-xs">
                <th className="py-2.5 px-4 font-semibold w-12 text-center">#</th>
                <th className="py-2.5 px-4 font-semibold">Wallet</th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("win_rate")}>
                  <div className="flex items-center justify-end gap-1">Win% {sortBy === "win_rate" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("winning_count")}>
                  <div className="flex items-center justify-end gap-1">Wins {sortBy === "winning_count" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("total_pnl")}>
                  <div className="flex items-center justify-end gap-1">{pnlWindow ? pnlWindowLabel : "PnL"} {sortBy === "total_pnl" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("roi_pct")}>
                  <div className="flex items-center justify-end gap-1">ROI {sortBy === "roi_pct" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("total_volume")}>
                  <div className="flex items-center justify-end gap-1">Volume {sortBy === "total_volume" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("resolved_count")}>
                  <div className="flex items-center justify-end gap-1">Resolved {sortBy === "resolved_count" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right">Avg Buy</th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleTradeSort("buys_below_10c")}
                >
                  <div className="flex flex-col items-center leading-tight">
                    <span className={`text-[10px] ${tradeSortKey === "buys_below_10c" ? "text-green-300" : "text-green-400"}`}>
                      &lt;0.10 {tradeSortKey === "buys_below_10c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                    <span className={`text-[10px] ${tradeSortKey === "wins_below_10c" ? "text-foreground" : "text-muted-fg"}`}>
                      W {tradeSortKey === "wins_below_10c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                  </div>
                </th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleTradeSort("buys_below_20c")}
                >
                  <div className="flex flex-col items-center leading-tight">
                    <span className={`text-[10px] ${tradeSortKey === "buys_below_20c" ? "text-green-300" : "text-green-400"}`}>
                      &lt;0.20 {tradeSortKey === "buys_below_20c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                    <span className={`text-[10px] ${tradeSortKey === "wins_below_20c" ? "text-foreground" : "text-muted-fg"}`}>
                      W {tradeSortKey === "wins_below_20c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                  </div>
                </th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleTradeSort("buys_below_30c")}
                >
                  <div className="flex flex-col items-center leading-tight">
                    <span className={`text-[10px] ${tradeSortKey === "buys_below_30c" ? "text-yellow-300" : "text-yellow-400"}`}>
                      &lt;0.30 {tradeSortKey === "buys_below_30c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                    <span className={`text-[10px] ${tradeSortKey === "wins_below_30c" ? "text-foreground" : "text-muted-fg"}`}>
                      W {tradeSortKey === "wins_below_30c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                  </div>
                </th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleTradeSort("buys_below_40c")}
                >
                  <div className="flex flex-col items-center leading-tight">
                    <span className={`text-[10px] ${tradeSortKey === "buys_below_40c" ? "text-orange-300" : "text-orange-400"}`}>
                      &lt;0.40 {tradeSortKey === "buys_below_40c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                    <span className={`text-[10px] ${tradeSortKey === "wins_below_40c" ? "text-foreground" : "text-muted-fg"}`}>
                      W {tradeSortKey === "wins_below_40c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                  </div>
                </th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none"
                  onClick={() => handleTradeSort("buys_above_70c")}
                >
                  <div className="flex flex-col items-center leading-tight">
                    <span className={`text-[10px] ${tradeSortKey === "buys_above_70c" ? "text-red-300" : "text-red-400"}`}>
                      &gt;0.70 {tradeSortKey === "buys_above_70c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                    <span className={`text-[10px] ${tradeSortKey === "wins_above_70c" ? "text-foreground" : "text-muted-fg"}`}>
                      W {tradeSortKey === "wins_above_70c" ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                    </span>
                  </div>
                </th>
                <th className="py-2.5 px-4 font-semibold text-right">Last Active</th>
              </tr>
            </thead>
            <tbody>
              {displayWallets.map((w, i) => {
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
                    <td className="py-2.5 px-4 text-right font-mono text-xs">
                      {w.avg_buy_price > 0 ? `${(Number(w.avg_buy_price) * 100).toFixed(0)}¢` : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                      <span className="text-green-400">{Number(w.buys_below_10c || 0)}</span>
                      <span className="text-muted-fg">/</span>
                      <span className="text-foreground">{Number(w.wins_below_10c || 0)}</span>
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                      <span className="text-green-400">{Number(w.buys_below_20c || 0)}</span>
                      <span className="text-muted-fg">/</span>
                      <span className="text-foreground">{Number(w.wins_below_20c || 0)}</span>
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                      <span className="text-yellow-400">{Number(w.buys_below_30c || 0)}</span>
                      <span className="text-muted-fg">/</span>
                      <span className="text-foreground">{Number(w.wins_below_30c || 0)}</span>
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                      <span className="text-orange-400">{Number(w.buys_below_40c || 0)}</span>
                      <span className="text-muted-fg">/</span>
                      <span className="text-foreground">{Number(w.wins_below_40c || 0)}</span>
                    </td>
                    <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                      <span className="text-red-400">{Number(w.buys_above_70c || 0)}</span>
                      <span className="text-muted-fg">/</span>
                      <span className="text-foreground">{Number(w.wins_above_70c || 0)}</span>
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono text-muted-fg text-xs">{(w.last_active || w.last_trade_at) ? new Date((w.last_active || w.last_trade_at) as string).toLocaleDateString() : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      <Pagination page={page} totalPages={totalPages} totalCount={total} onPageChange={setPage} />
    </div>
  );
}
