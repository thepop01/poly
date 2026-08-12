"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { getWalletCounts, getSubcategories } from "@/utils/api";
import { formatCurrency, timeAgo } from "@/utils/format";
import { useWalletList } from "@/hooks/useWalletList";
import { useCopyAddress } from "@/hooks/useCopyAddress";
import { useWatchlistAdd } from "@/hooks/useWatchlistAdd";
import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";
import { WalletTable, WalletRow, ColumnDef } from "@/components/wallets/WalletTable";
import { WalletCell } from "@/components/wallets/WalletCell";
import { Pagination } from "@/components/wallets/Pagination";
import { StatCard, StatCardRow } from "@/components/ui/StatCard";
import { PillTabs } from "@/components/ui/PillTabs";
import { Globe as GlobeIcon, Activity, Moon, Sparkles, BarChart2 } from "lucide-react";

const ACTIVE_TABS = [
  { key: "all", label: "All", description: "Every tracked wallet that isn't dead" },
  { key: "curated", label: "Curated", description: "Top performing & manually curated smart money wallets" },
  { key: "standard", label: "Standard", description: "Balance + positions ≥ $1k with trading history — active whales" },
  { key: "low_balance", label: "Low Balance", description: "Balance + positions under $1k" },
  { key: "new", label: "New", description: "Funded with $1k+ but hasn't made a trade yet" },
] as const;

const HIBERNATED_TABS = [
  { key: "hibernated", label: "Hibernated", description: "No trades in 30+ days" },
] as const;

const TABS = [...ACTIVE_TABS, ...HIBERNATED_TABS] as const;

type TabKey = (typeof TABS)[number]["key"];

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

const PNL_WINDOW_OPTIONS = [
  { value: "", label: "Last 5000" },
  { value: "pnl_3500", label: "Last 3500" },
  { value: "pnl_2000", label: "Last 2000" },
  { value: "pnl_1500", label: "Last 1500" },
  { value: "pnl_1000", label: "Last 1000" },
  { value: "pnl_750", label: "Last 750" },
  { value: "pnl_500", label: "Last 500" },
  { value: "pnl_300", label: "Last 300" },
  { value: "pnl_200", label: "Last 200" },
  { value: "pnl_100", label: "Last 100" },
];

const DEFAULT_SORT: Record<TabKey, { field: string; order: "asc" | "desc" }> = {
  all: { field: "pnl", order: "desc" },
  curated: { field: "pnl", order: "desc" },
  standard: { field: "pnl", order: "desc" },
  low_balance: { field: "pnl", order: "desc" },
  new: { field: "added_at", order: "desc" },
  hibernated: { field: "last_trade_at", order: "asc" },
};

const PAGE_SIZE = 50;

function num(v: string | number | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return isNaN(n) ? null : n;
}

function signedCurrency(v: string | number | null | undefined, bold = false) {
  const n = num(v);
  if (n == null) return <>—</>;
  return (
    <span className={`${n >= 0 ? "text-green-500" : "text-red-500"} ${bold ? "font-bold" : ""}`}>
      {n > 0 ? "+" : ""}
      {formatCurrency(n)}
    </span>
  );
}

function plainCurrency(v: string | number | null | undefined) {
  const n = num(v);
  if (n == null) return <>—</>;
  return <span className={n >= 0 ? "text-green-500" : "text-red-500"}>{formatCurrency(n)}</span>;
}

function relativeDate(v: string | null | undefined) {
  const t = timeAgo(v);
  if (!t) return <>—</>;
  return (
    <span title={t.absolute} className="text-muted-fg">
      {t.relative}
    </span>
  );
}

function WalletsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabKey = (TABS.find((t) => t.key === tabParam)?.key as TabKey) || "all";

  const [sortField, setSortField] = useState(DEFAULT_SORT[tab].field);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(DEFAULT_SORT[tab].order);
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [analyticsTab, setAnalyticsTab] = useState(false);
  const [tradeSortKey, setTradeSortKey] = useState<string | null>(null);
  const [tradeSortDir, setTradeSortDir] = useState<"desc" | "asc">("desc");

  const [category, setCategory] = useState("OVERALL");
  const [filterSubcategory, setFilterSubcategory] = useState("");
  const [subcategoryOptions, setSubcategoryOptions] = useState<string[]>([]);
  const [pnlWindow, setPnlWindow] = useState("");

  const { copiedAddress, handleCopy } = useCopyAddress();
  const { watchlistStatus, handleAddToWatchlist } = useWatchlistAdd();

  const TRADE_SORT_CYCLE: Record<string, [string, "desc" | "asc"][]> = {
    buys_below_15c: [["buys_below_15c", "desc"], ["wins_below_15c", "desc"], ["wins_below_15c", "asc"], ["buys_below_15c", "asc"]],
    buys_15_30c: [["buys_15_30c", "desc"], ["wins_15_30c", "desc"], ["wins_15_30c", "asc"], ["buys_15_30c", "asc"]],
    buys_30_45c: [["buys_30_45c", "desc"], ["wins_30_45c", "desc"], ["wins_30_45c", "asc"], ["buys_30_45c", "asc"]],
    buys_45_60c: [["buys_45_60c", "desc"], ["wins_45_60c", "desc"], ["wins_45_60c", "asc"], ["buys_45_60c", "asc"]],
    buys_60_75c: [["buys_60_75c", "desc"], ["wins_60_75c", "desc"], ["wins_60_75c", "asc"], ["buys_60_75c", "asc"]],
    buys_above_75c: [["buys_above_75c", "desc"], ["wins_above_75c", "desc"], ["wins_above_75c", "asc"], ["buys_above_75c", "asc"]],
  };

  const handleTradeSort = (key: string) => {
    const cycle = TRADE_SORT_CYCLE[key];
    if (!cycle) return;
    const currentIdx = cycle.findIndex(([k, d]) => k === sortField && d === sortOrder);
    const nextIdx = (currentIdx + 1) % cycle.length;
    const [nextKey, nextDir] = cycle[nextIdx];
    setSortField(nextKey);
    setSortOrder(nextDir);
    setTradeSortKey(nextKey);
    setTradeSortDir(nextDir);
    setPage(1);
  };

  useEffect(() => {
    getWalletCounts().then(setCounts).catch(() => setCounts(null));
  }, []);

  // Fetch subcategories when category changes
  useEffect(() => {
    if (category === "OVERALL") {
      setSubcategoryOptions([]);
      setFilterSubcategory("");
      return;
    }
    getSubcategories(category)
      .then((data) => {
        setSubcategoryOptions(data.subcategories || []);
        setFilterSubcategory("");
      })
      .catch(() => {
        setSubcategoryOptions([]);
        setFilterSubcategory("");
      });
  }, [category]);

  // Reset paging/sort when the tab changes
  useEffect(() => {
    setSortField(DEFAULT_SORT[tab].field);
    setSortOrder(DEFAULT_SORT[tab].order);
    setPage(1);
  }, [tab]);

  const isHibernated = tab === "hibernated";
  const isAnalyticsView = analyticsTab && !isHibernated;

  const { wallets, total, loading } = useWalletList({
    tab,
    source: sourceFilter || undefined,
    category: !isHibernated && category !== "OVERALL" ? category : undefined,
    subcategory: !isHibernated && filterSubcategory ? filterSubcategory : undefined,
    pnl_window: !isHibernated && pnlWindow ? pnlWindow : undefined,
    search: searchQuery || undefined,
    sort_by: sortField,
    sort_order: sortOrder,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const walletAddresses = useMemo(() => wallets.map((w) => w.address), [wallets]);
  const { isLiked, toggleLike } = useFavoriteToggle(walletAddresses);

  const switchTab = (key: TabKey) => {
    router.replace(key === "all" ? "/wallets" : `/wallets?tab=${key}`, { scroll: false });
  };

  const handleSort = (key: string) => {
    if (sortField === key) {
      setSortOrder(sortOrder === "desc" ? "asc" : "desc");
    } else {
      setSortField(key);
      setSortOrder("desc");
    }
    setPage(1);
  };

  const columns = useMemo<ColumnDef[]>(() => {
    const wallet: ColumnDef = {
      key: "wallet",
      label: "Wallet",
      align: "left",
      render: (w: WalletRow) => (
        <WalletCell
          address={w.address}
          username={w.username}
          copiedAddress={copiedAddress}
          onCopy={handleCopy}
          watchlistStatus={watchlistStatus}
          onAddToWatchlist={handleAddToWatchlist}
        />
      ),
    };

    const sourceCol: ColumnDef = {
      key: "source",
      label: "Source",
      align: "center",
      render: (w: WalletRow) => {
        const rawTier = (w.tier || "").toUpperCase();
        let badgeStyle = "bg-blue-500/10 text-blue-400 border-blue-500/20";
        let label = "Standard";

        if (rawTier === "CURATED") {
          badgeStyle = "bg-yellow-500/10 text-yellow-400 border-yellow-500/20";
          label = "Curated";
        } else if (rawTier === "PREVIOUSLY_CURATED") {
          badgeStyle = "bg-amber-500/10 text-amber-400 border-amber-500/20";
          label = "Prev Curated";
        } else if (rawTier === "LOW_BALANCE") {
          badgeStyle = "bg-purple-500/10 text-purple-400 border-purple-500/20";
          label = "Low Balance";
        } else if (rawTier === "NEW") {
          badgeStyle = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
          label = "New";
        } else if (rawTier === "DEAD") {
          badgeStyle = "bg-red-500/10 text-red-400 border-red-500/20";
          label = "Dead";
        } else if (w.sources?.includes("custom")) {
          badgeStyle = "bg-cyan-500/10 text-cyan-400 border-cyan-500/20";
          label = "Custom";
        }

        return (
          <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
            {label}
          </span>
        );
      },
    };

    if (isAnalyticsView) {
      const avgBuyPrice: ColumnDef = {
        key: "avg_buy_price",
        label: "Avg Buy",
        sortable: true,
        render: (w) => {
          const bp = num(w.avg_buy_price);
          return bp && bp > 0 ? `${(bp * 100).toFixed(0)}¢` : "—";
        },
      };

      const makeBucketCol = (key: string, title: string, colorClass: string, buysKey: keyof WalletRow, winsKey: keyof WalletRow): ColumnDef => ({
        key,
        align: "center",
        label: (
          <div className="flex items-center justify-center gap-1 cursor-pointer select-none whitespace-nowrap" onClick={() => handleTradeSort(key)}>
            <span className={`text-[10px] ${tradeSortKey === key || tradeSortKey === winsKey ? "text-foreground font-bold" : colorClass}`}>
              {title} W/R {tradeSortKey === key || tradeSortKey === winsKey ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
            </span>
          </div>
        ),
        render: (w) => (
          <div className="flex items-center justify-center gap-0.5 text-[11px] font-mono">
            <span className={colorClass}>{num(w[buysKey] as string | number | null | undefined) || 0}</span>
            <span className="text-muted-fg">/</span>
            <span className="text-foreground">{num(w[winsKey] as string | number | null | undefined) || 0}</span>
          </div>
        ),
      });

      const lastTraded: ColumnDef = {
        key: "last_trade_at",
        label: "Last Active",
        sortable: true,
        render: (w) => relativeDate(w.last_trade_at),
      };

      return [
        wallet,
        sourceCol,
        avgBuyPrice,
        makeBucketCol("buys_below_15c", "<0.15", "text-green-400", "buys_below_15c", "wins_below_15c"),
        makeBucketCol("buys_15_30c", "0.15-0.30", "text-emerald-400", "buys_15_30c", "wins_15_30c"),
        makeBucketCol("buys_30_45c", "0.30-0.45", "text-yellow-400", "buys_30_45c", "wins_30_45c"),
        makeBucketCol("buys_45_60c", "0.45-0.60", "text-orange-400", "buys_45_60c", "wins_45_60c"),
        makeBucketCol("buys_60_75c", "0.60-0.75", "text-red-400", "buys_60_75c", "wins_60_75c"),
        makeBucketCol("buys_above_75c", ">0.75", "text-rose-500", "buys_above_75c", "wins_above_75c"),
        lastTraded,
      ];
    }

    const winRate: ColumnDef = {
      key: "win_rate",
      label: "Win%",
      sortable: true,
      render: (w) => {
        const wr = num(w.win_rate);
        if (wr == null) return <>—</>;
        return `${(wr * 100).toFixed(0)}%`;
      },
    };

    const wins: ColumnDef = {
      key: "winning_count",
      label: "Wins",
      sortable: true,
      render: (w) => num(w.winning_count) || 0,
    };

    const pnl: ColumnDef = { key: "pnl", label: "PnL", sortable: true, render: (w) => signedCurrency(w.pnl, true) };

    const roi: ColumnDef = {
      key: "roi",
      label: "ROI",
      sortable: true,
      render: (w) => {
        const n = num(w.roi_pct);
        if (n == null) return <>—</>;
        return (
          <span className={n >= 0 ? "text-green-500" : "text-red-500"}>
            {n > 0 ? "+" : ""}
            {n.toFixed(2)}%
          </span>
        );
      },
    };

    const volume: ColumnDef = {
      key: "volume",
      label: "Volume",
      sortable: true,
      render: (w) => {
        const n = num(w.volume);
        return n == null ? <>—</> : <>{formatCurrency(n)}</>;
      },
    };

    const balance: ColumnDef = { key: "balance", label: "Balance", sortable: true, render: (w) => plainCurrency(w.balance) };
    const position: ColumnDef = {
      key: "position_value",
      label: "Open Pos",
      sortable: true,
      render: (w) => plainCurrency(w.position_value),
    };

    const resolved: ColumnDef = {
      key: "resolved_count",
      label: "Resolved",
      sortable: true,
      render: (w) => num(w.resolved_count) || 0,
    };

    const lastTraded: ColumnDef = {
      key: "last_trade_at",
      label: "Last Active",
      sortable: true,
      render: (w) => relativeDate(w.last_trade_at),
    };

    return [wallet, sourceCol, winRate, wins, pnl, roi, volume, balance, position, resolved, lastTraded];
  }, [isAnalyticsView, tradeSortKey, tradeSortDir, copiedAddress, handleCopy, watchlistStatus, handleAddToWatchlist]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const activeTab = TABS.find((t) => t.key === tab)!;
  const activeCount = counts ? counts.all - counts.hibernated : null;
  const inactiveCount = counts ? counts.hibernated : null;

  const tabCount = (key: TabKey) => {
    if (!counts) return null;
    return key === "all" ? counts.all : counts[key];
  };

  return (
    <div className="w-full h-full flex flex-col bg-background">
      {/* Tab bar */}
      <div className="flex items-center gap-6 mb-3 flex-wrap border-b border-border/60 pb-3">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="text-xs font-bold text-muted-fg uppercase tracking-wider">Active Category:</span>
          <PillTabs
            tabs={ACTIVE_TABS.map((t) => ({ key: t.key, label: t.label, count: tabCount(t.key) }))}
            active={tab}
            onChange={(k) => switchTab(k as TabKey)}
          />
        </div>
        <div className="h-6 w-px bg-border hidden sm:block" />
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="text-xs font-bold text-muted-fg uppercase tracking-wider">Hibernated:</span>
          <PillTabs
            tabs={HIBERNATED_TABS.map((t) => ({ key: t.key, label: t.label, count: tabCount(t.key) }))}
            active={tab}
            onChange={(k) => switchTab(k as TabKey)}
          />
        </div>
      </div>
      <p className="text-xs text-subtle flex-shrink-0 mb-3">{activeTab.description}</p>

      {/* Category tabs & PnL Windows (Hidden for Hibernated) */}
      {!isHibernated && (
        <div className="flex flex-col gap-3 flex-shrink-0 border-b border-border w-full pb-3 mb-3">
          <div className="flex items-center gap-4 flex-wrap">
            {CATEGORY_TABS.map((cat) => (
              <button
                key={cat.key}
                onClick={() => { setCategory(cat.key); setPage(1); setSortField("pnl"); }}
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
          <div className="flex items-center gap-4 flex-wrap">
            {/* Step Slider Control */}
            <div className="flex items-center gap-3 bg-surface-2/60 border border-border px-3 py-1.5 rounded-xl">
              <span className="text-xs font-semibold text-muted-fg uppercase tracking-wider">Sample Range:</span>
              <input
                type="range"
                min={0}
                max={PNL_WINDOW_OPTIONS.length - 1}
                step={1}
                value={
                  // Reverse index so 100 is left and 5000 is right
                  [...PNL_WINDOW_OPTIONS].reverse().findIndex(opt => opt.value === pnlWindow) === -1
                    ? PNL_WINDOW_OPTIONS.length - 1
                    : [...PNL_WINDOW_OPTIONS].reverse().findIndex(opt => opt.value === pnlWindow)
                }
                onChange={(e) => {
                  const reversed = [...PNL_WINDOW_OPTIONS].reverse();
                  const idx = parseInt(e.target.value, 10);
                  const selected = reversed[idx];
                  if (selected) {
                    setPnlWindow(selected.value);
                    setPage(1);
                  }
                }}
                className="w-36 accent-blue-500 cursor-pointer h-1.5 bg-surface-3 rounded-lg"
              />
              <span className="text-xs font-bold text-blue-400 min-w-[70px]">
                {PNL_WINDOW_OPTIONS.find(opt => opt.value === pnlWindow)?.label || "Last 5000"}
              </span>
            </div>

            {/* Quick Snap Pills */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {PNL_WINDOW_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => { 
                    setPnlWindow(opt.value);
                    setPage(1); 
                  }}
                  className={`px-2.5 py-1 text-[11px] font-semibold transition-all rounded-lg uppercase tracking-wider ${
                    pnlWindow === opt.value
                      ? "bg-blue-500/20 text-blue-400 border border-blue-500/30 shadow-sm"
                      : "text-muted-fg bg-surface-2 hover:bg-surface-3 border border-transparent"
                  }`}
                >
                  {opt.label.replace("Last ", "")}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Subcategory Pills + Search + Analytics toggle */}
      <div className="flex items-center justify-between flex-shrink-0 mb-3 gap-4">
        {!isHibernated && subcategoryOptions.length > 0 ? (
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
        ) : (
          <div className="flex-1" />
        )}

        <div className="flex items-center gap-2 ml-auto flex-shrink-0">
          {!isHibernated && (
            <button
              onClick={() => setAnalyticsTab(!analyticsTab)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors uppercase tracking-wider ${
                analyticsTab
                  ? "bg-purple-500/15 text-purple-400 border border-purple-500/30"
                  : "bg-surface text-muted-fg hover:text-foreground border border-border"
              }`}
            >
              <BarChart2 size={14} />
              {analyticsTab ? "Analytics View" : "Analytics"}
            </button>
          )}

          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-subtle" />
            <input
              type="text"
              placeholder="Search address or username..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              className="bg-surface border border-border rounded-lg pl-9 pr-3 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder-subtle w-56 font-mono"
            />
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto bg-surface rounded-xl border border-border">
        {loading ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm py-12">Loading...</div>
        ) : wallets.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-fg text-sm py-12">
            No wallets found
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[1100px]">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-surface text-muted-fg font-mono uppercase tracking-wider text-xs">
                  <th className="py-2.5 px-4 font-semibold w-12 text-center">#</th>
                  <th className="py-2.5 px-4 font-semibold">Wallet</th>
                  <th className="py-2.5 px-4 font-semibold text-center">Source</th>
                  {!isAnalyticsView ? (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("win_rate")}>
                        <div className="flex items-center justify-end gap-1">Win% {sortField === "win_rate" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("winning_count")}>
                        <div className="flex items-center justify-end gap-1">Wins {sortField === "winning_count" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("pnl")}>
                        <div className="flex items-center justify-end gap-1">PnL {sortField === "pnl" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("roi")}>
                        <div className="flex items-center justify-end gap-1">ROI {sortField === "roi" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("volume")}>
                        <div className="flex items-center justify-end gap-1">Volume {sortField === "volume" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("balance")}>
                        <div className="flex items-center justify-end gap-1">Balance {sortField === "balance" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("position_value")}>
                        <div className="flex items-center justify-end gap-1">Open Pos {sortField === "position_value" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("resolved_count")}>
                        <div className="flex items-center justify-end gap-1">Resolved {sortField === "resolved_count" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                    </>
                  ) : (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("avg_buy_price")}>
                        <div className="flex items-center justify-end gap-1">Avg Buy {sortField === "avg_buy_price" && (sortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_below_15c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_below_15c" || tradeSortKey === "wins_below_15c" ? "text-foreground font-bold" : "text-green-400"}`}>
                          &lt;0.15 W/R {(tradeSortKey === "buys_below_15c" || tradeSortKey === "wins_below_15c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_15_30c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_15_30c" || tradeSortKey === "wins_15_30c" ? "text-foreground font-bold" : "text-emerald-400"}`}>
                          0.15-0.30 W/R {(tradeSortKey === "buys_15_30c" || tradeSortKey === "wins_15_30c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_30_45c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_30_45c" || tradeSortKey === "wins_30_45c" ? "text-foreground font-bold" : "text-yellow-400"}`}>
                          0.30-0.45 W/R {(tradeSortKey === "buys_30_45c" || tradeSortKey === "wins_30_45c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_45_60c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_45_60c" || tradeSortKey === "wins_45_60c" ? "text-foreground font-bold" : "text-orange-400"}`}>
                          0.45-0.60 W/R {(tradeSortKey === "buys_45_60c" || tradeSortKey === "wins_45_60c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_60_75c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_60_75c" || tradeSortKey === "wins_60_75c" ? "text-foreground font-bold" : "text-red-400"}`}>
                          0.60-0.75 W/R {(tradeSortKey === "buys_60_75c" || tradeSortKey === "wins_60_75c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                      <th className="py-2.5 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_above_75c")}>
                        <span className={`text-[10px] ${tradeSortKey === "buys_above_75c" || tradeSortKey === "wins_above_75c" ? "text-foreground font-bold" : "text-rose-500"}`}>
                          &gt;0.75 W/R {(tradeSortKey === "buys_above_75c" || tradeSortKey === "wins_above_75c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </span>
                      </th>
                    </>
                  )}
                  <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("last_trade_at")}>
                    <div className="flex items-center justify-end gap-1">
                      Last Active {sortField === "last_trade_at" && (sortOrder === "desc" ? "↓" : "↑")}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {wallets.map((w, i) => {
                  const pnlVal = num(w.pnl) || 0;
                  const roiVal = num(w.roi_pct) || 0;
                  const rawTier = (w.tier || "").toUpperCase();
                  let badgeStyle = "bg-blue-500/10 text-blue-400 border-blue-500/20";
                  let label = "Standard";
                  if (rawTier === "CURATED") {
                    badgeStyle = "bg-yellow-500/10 text-yellow-400 border-yellow-500/20";
                    label = "Curated";
                  } else if (rawTier === "PREVIOUSLY_CURATED") {
                    badgeStyle = "bg-amber-500/10 text-amber-400 border-amber-500/20";
                    label = "Prev Curated";
                  } else if (rawTier === "LOW_BALANCE") {
                    badgeStyle = "bg-purple-500/10 text-purple-400 border-purple-500/20";
                    label = "Low Balance";
                  } else if (rawTier === "NEW") {
                    badgeStyle = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
                    label = "New";
                  } else if (rawTier === "DEAD") {
                    badgeStyle = "bg-red-500/10 text-red-400 border-red-500/20";
                    label = "Dead";
                  } else if (w.sources?.includes("custom")) {
                    badgeStyle = "bg-cyan-500/10 text-cyan-400 border-cyan-500/20";
                    label = "Custom";
                  }

                  return (
                    <tr key={w.address} className="border-b border-border hover:bg-background/50 transition-colors">
                      <td className="py-2.5 px-4 text-center font-medium text-muted-fg">{(page - 1) * PAGE_SIZE + i + 1}</td>
                      <td className="py-2.5 px-4 font-medium text-foreground">
                        <WalletCell
                          address={w.address}
                          username={w.username}
                          copiedAddress={copiedAddress}
                          onCopy={handleCopy}
                          watchlistStatus={watchlistStatus}
                          onAddToWatchlist={handleAddToWatchlist}
                          isLiked={isLiked(w.address)}
                          onToggleLike={(e, addr) => toggleLike(addr, e)}
                          favoriteCount={num(w.favorite_count) || undefined}
                        />
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
                          {label}
                        </span>
                      </td>
                      {!isAnalyticsView ? (
                        <>
                          <td className="py-2.5 px-4 text-right font-mono">
                            {w.win_rate != null ? `${(Number(w.win_rate) * 100).toFixed(0)}%` : "—"}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">{num(w.winning_count) || 0}</td>
                          <td className={`py-2.5 px-4 text-right font-mono font-bold ${pnlVal >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {pnlVal > 0 ? "+" : ""}{formatCurrency(pnlVal)}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">
                            <span className={roiVal >= 0 ? "text-green-500" : "text-red-500"}>
                              {roiVal > 0 ? "+" : ""}{roiVal.toFixed(2)}%
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(num(w.volume) || 0)}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(num(w.balance) || 0)}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(num(w.position_value) || 0)}</td>
                          <td className="py-2.5 px-4 text-right font-mono">{num(w.resolved_count) || 0}</td>
                        </>
                      ) : (
                        <>
                          <td className="py-2.5 px-4 text-right font-mono text-xs">
                            {num(w.avg_buy_price) && Number(w.avg_buy_price) > 0 ? `${(Number(w.avg_buy_price) * 100).toFixed(0)}¢` : "—"}
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-green-400">{num(w.buys_below_15c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_below_15c) || 0}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-emerald-400">{num(w.buys_15_30c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_15_30c) || 0}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-yellow-400">{num(w.buys_30_45c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_30_45c) || 0}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-orange-400">{num(w.buys_45_60c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_45_60c) || 0}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-red-400">{num(w.buys_60_75c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_60_75c) || 0}</span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px]">
                            <span className="text-rose-500">{num(w.buys_above_75c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.wins_above_75c) || 0}</span>
                          </td>
                        </>
                      )}
                      <td className="py-2.5 px-4 text-right font-mono text-muted-fg text-xs">
                        {w.last_trade_at ? new Date(w.last_trade_at as string).toLocaleDateString() : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pagination page={page} totalPages={totalPages} totalCount={total} onPageChange={setPage} />
    </div>
  );
}

export default function WalletsPage() {
  return (
    <Suspense fallback={null}>
      <WalletsPageInner />
    </Suspense>
  );
}
