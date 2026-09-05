"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { getSubcategories, getLeagues } from "@/utils/api";
import { formatCurrency, timeAgo, formatPercent, formatPriceCents } from "@/utils/format";
import { useWalletList } from "@/hooks/useWalletList";
import { useCopyAddress } from "@/hooks/useCopyAddress";
import { useWatchlistAdd } from "@/hooks/useWatchlistAdd";
import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";
import { WalletTable, WalletRow, ColumnDef } from "@/components/wallets/WalletTable";
import { WalletCell } from "@/components/wallets/WalletCell";
import { Pagination } from "@/components/wallets/Pagination";
import { ViewDropdown, WalletViewMode } from "@/components/wallets/ViewDropdown";
import { TABS, TabKey } from "@/components/wallets/WalletTierTabs";

const TAB_DESCRIPTIONS: Record<TabKey, string> = {
  all: "Every tracked wallet that isn't dead",
  curated: "Top performing & manually curated smart money wallets",
  standard: "Balance + positions ≥ $1k with trading history — active whales",
  low_balance: "Balance + positions under $1k",
  new: "Funded with $1k+ but hasn't made a trade yet",
  hibernated: "No trades in 30+ days",
};

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
  { value: "", label: "All" },
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
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tab: TabKey = (TABS.find((t) => t.key === tabParam)?.key as TabKey) || "all";

  // Shared state for General and Analytics views
  const [sortField, setSortField] = useState(DEFAULT_SORT[tab].field);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">(DEFAULT_SORT[tab].order);
  const [page, setPage] = useState(1);

  // Independent state for Parlay view
  const [parlaySortField, setParlaySortField] = useState("parlay_pnl");
  const [parlaySortOrder, setParlaySortOrder] = useState<"asc" | "desc">("desc");
  const [parlayPage, setParlayPage] = useState(1);

  // Independent state for Lineage view
  const [lineageSortField, setLineageSortField] = useState("p2p_txn_value");
  const [lineageSortOrder, setLineageSortOrder] = useState<"asc" | "desc">("desc");
  const [lineagePage, setLineagePage] = useState(1);

  const [searchQuery, setSearchQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [viewMode, setViewMode] = useState<WalletViewMode>("general");
  const [tradeSortKey, setTradeSortKey] = useState<string | null>(null);
  const [tradeSortDir, setTradeSortDir] = useState<"desc" | "asc">("desc");

  const [category, setCategory] = useState("OVERALL");
  const [filterSubcategory, setFilterSubcategory] = useState("");
  const [subcategoryOptions, setSubcategoryOptions] = useState<string[]>([]);
  const [filterLeague, setFilterLeague] = useState("");
  const [leagueOptions, setLeagueOptions] = useState<string[]>([]);
  const [pnlWindow, setPnlWindow] = useState("");

  const { copiedAddress, handleCopy } = useCopyAddress();
  const { watchlistStatus, handleAddToWatchlist } = useWatchlistAdd();

  const isHibernated = tab === "hibernated";
  const currentViewMode: WalletViewMode = isHibernated ? "general" : viewMode;
  const isAnalyticsView = currentViewMode === "analytics";
  const isParlayView = currentViewMode === "parlay";
  const isLineageView = currentViewMode === "lineage";

  const activeSortField = isParlayView ? parlaySortField : isLineageView ? lineageSortField : sortField;
  const activeSortOrder = isParlayView ? parlaySortOrder : isLineageView ? lineageSortOrder : sortOrder;
  const activePage = isParlayView ? parlayPage : isLineageView ? lineagePage : page;
  const activeSetPage = isParlayView ? setParlayPage : isLineageView ? setLineagePage : setPage;

  const TRADE_SORT_CYCLE: Record<string, [string, "desc" | "asc"][]> = {
    buys_below_15c: [["buys_below_15c", "desc"], ["wins_below_15c", "desc"], ["wins_below_15c", "asc"], ["buys_below_15c", "asc"]],
    buys_15_30c: [["buys_15_30c", "desc"], ["wins_15_30c", "desc"], ["wins_15_30c", "asc"], ["buys_15_30c", "asc"]],
    buys_30_45c: [["buys_30_45c", "desc"], ["wins_30_45c", "desc"], ["wins_30_45c", "asc"], ["buys_30_45c", "asc"]],
    buys_45_60c: [["buys_45_60c", "desc"], ["wins_45_60c", "desc"], ["wins_45_60c", "asc"], ["buys_45_60c", "asc"]],
    buys_60_75c: [["buys_60_75c", "desc"], ["wins_60_75c", "desc"], ["wins_60_75c", "asc"], ["buys_60_75c", "asc"]],
    buys_above_75c: [["buys_above_75c", "desc"], ["wins_above_75c", "desc"], ["wins_above_75c", "asc"], ["buys_above_75c", "asc"]],
  };

  const resetAllPages = () => {
    setPage(1);
    setParlayPage(1);
    setLineagePage(1);
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
    resetAllPages();
  };

  useEffect(() => {
    if (category === "OVERALL") {
      setSubcategoryOptions([]);
      setFilterSubcategory("");
      setLeagueOptions([]);
      setFilterLeague("");
      return;
    }
    getSubcategories(category)
      .then((data) => {
        setSubcategoryOptions(data.subcategories || []);
        setFilterSubcategory("");
        setLeagueOptions([]);
        setFilterLeague("");
      })
      .catch(() => {
        setSubcategoryOptions([]);
        setFilterSubcategory("");
        setLeagueOptions([]);
        setFilterLeague("");
      });
  }, [category]);

  // Fetch leagues when subcategory changes (Tier 3)
  useEffect(() => {
    if (category === "OVERALL" || !filterSubcategory) {
      setLeagueOptions([]);
      setFilterLeague("");
      return;
    }
    getLeagues(category, filterSubcategory)
      .then((data) => {
        setLeagueOptions(data.leagues || []);
        setFilterLeague("");
      })
      .catch(() => {
        setLeagueOptions([]);
        setFilterLeague("");
      });
  }, [category, filterSubcategory]);

  // Reset paging/sort only when the main tab changes (All / Curated / Standard / etc.)
  useEffect(() => {
    setSortField(DEFAULT_SORT[tab].field);
    setSortOrder(DEFAULT_SORT[tab].order);
    setParlaySortField("parlay_pnl");
    setParlaySortOrder("desc");
    setLineageSortField("p2p_txn_value");
    setLineageSortOrder("desc");
    resetAllPages();
  }, [tab]);

  const { wallets, total, loading } = useWalletList({
    tab,
    source: sourceFilter || undefined,
    category: !isHibernated && category !== "OVERALL" ? category : undefined,
    subcategory: !isHibernated && filterSubcategory ? filterSubcategory : undefined,
    league: !isHibernated && filterLeague ? filterLeague : undefined,
    pnl_window: !isHibernated && !isParlayView && pnlWindow ? pnlWindow : undefined,
    view_type: isParlayView ? "parlay" : isLineageView ? "lineage" : undefined,
    has_lineage: isLineageView || undefined,
    search: searchQuery || undefined,
    sort_by: activeSortField,
    sort_order: activeSortOrder,
    limit: PAGE_SIZE,
    offset: (activePage - 1) * PAGE_SIZE,
  });

  const walletAddresses = useMemo(() => wallets.map((w) => w.address), [wallets]);
  const { isLiked, toggleLike } = useFavoriteToggle(walletAddresses);

  const handleSort = (key: string) => {
    if (isParlayView) {
      if (parlaySortField === key) {
        setParlaySortOrder(parlaySortOrder === "desc" ? "asc" : "desc");
      } else {
        setParlaySortField(key);
        setParlaySortOrder("desc");
      }
      setParlayPage(1);
    } else if (isLineageView) {
      if (lineageSortField === key) {
        setLineageSortOrder(lineageSortOrder === "desc" ? "asc" : "desc");
      } else {
        setLineageSortField(key);
        setLineageSortOrder("desc");
      }
      setLineagePage(1);
    } else {
      if (sortField === key) {
        setSortOrder(sortOrder === "desc" ? "asc" : "desc");
      } else {
        setSortField(key);
        setSortOrder("desc");
      }
      setPage(1);
    }
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

        if (w.funding_source === "inherited_positions" || (num(w.transferred_positions_count) || 0) > 0) {
          const count = num(w.transferred_positions_count) || 0;
          return (
            <span 
              title={`Inherited ${count} positions via P2P transfers`}
              className="inline-block px-2 py-0.5 text-[11px] font-semibold rounded border bg-purple-500/15 text-purple-300 border-purple-500/30 shadow-sm"
            >
              Inherited ({count})
            </span>
          );
        }

        if (w.funding_source === "internal_funded" || w.funded_by) {
          return (
            <span 
              title={`Funded by ${w.funded_by || "Internal Wallet"}`}
              className="inline-block px-2 py-0.5 text-[11px] font-semibold rounded border bg-surface-2 text-foreground border-border"
            >
              Funded
            </span>
          );
        }

        if (rawTier === "CURATED") {
          badgeStyle = "bg-surface-2 text-foreground border-border font-bold";
          label = "Curated";
        } else if (rawTier === "LOW_BALANCE") {
          badgeStyle = "bg-surface-2 text-muted-fg border-border";
          label = "Low Balance";
        } else if (rawTier === "NEW") {
          badgeStyle = "bg-surface-2 text-muted-fg border-border";
          label = "New";
        } else if (rawTier === "DEAD") {
          badgeStyle = "bg-surface-2 text-muted-fg border-border";
          label = "Dead";
        } else if (w.sources?.includes("custom")) {
          badgeStyle = "bg-surface-2 text-muted-fg border-border";
          label = "Custom";
        }

        return (
          <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
            {label}
          </span>
        );
      },
    };

    if (isParlayView) {
      const winRate: ColumnDef = {
        key: "parlay_win_rate",
        label: "Win%",
        sortable: true,
        render: (w) => {
          const wr = num(w.parlay_win_rate);
          if (wr == null) return <>—</>;
          return `${wr.toFixed(0)}%`;
        },
      };

      const wins: ColumnDef = {
        key: "parlay_winning_count",
        label: "Wins",
        sortable: true,
        render: (w) => num(w.parlay_winning_count) || 0,
      };

      const resolved: ColumnDef = {
        key: "parlay_resolved_count",
        label: "Resolved",
        sortable: true,
        render: (w) => num(w.parlay_resolved_count) || 0,
      };

      const pnl: ColumnDef = {
        key: "parlay_pnl",
        label: "Parlay PnL",
        sortable: true,
        render: (w) => signedCurrency(w.parlay_pnl, true),
      };

      const volume: ColumnDef = {
        key: "parlay_volume",
        label: "Parlay Vol",
        sortable: true,
        render: (w) => {
          const n = num(w.parlay_volume);
          return n == null ? <>—</> : <>{formatCurrency(n)}</>;
        },
      };

      const openParlays: ColumnDef = {
        key: "parlay_open_count",
        label: "Open Parlays",
        sortable: true,
        render: (w) => {
          const count = num(w.parlay_open_count) || 0;
          const val = num(w.parlay_open_value) || 0;
          if (count === 0 && val === 0) {
            return <span className="font-mono text-muted-fg">—</span>;
          }
          return (
            <div className="flex items-center justify-end gap-1.5 font-mono text-xs whitespace-nowrap">
              <span className="font-semibold text-foreground">
                {count} {count === 1 ? "bet" : "bets"}
              </span>
              <span className="text-muted-fg text-[11px]">
                ({formatCurrency(val)})
              </span>
            </div>
          );
        },
      };

      const lastTraded: ColumnDef = {
        key: "last_trade_at",
        label: "Last Active",
        sortable: true,
        render: (w) => relativeDate(w.last_trade_at),
      };

      return [wallet, sourceCol, winRate, wins, resolved, pnl, volume, openParlays, lastTraded];
    }

    if (isLineageView) {
      const inlineValueCount = (val: number, count: number, colorClass: string) => (
        <div className="flex items-center justify-end gap-1.5 font-mono text-xs whitespace-nowrap">
          <span className={`font-bold ${colorClass}`}>
            {formatCurrency(val)}
          </span>
          <span className="text-muted-fg font-normal">-</span>
          <span className="text-muted-fg">
            {count} txns
          </span>
        </div>
      );

      const p2pTxnCol: ColumnDef = {
        key: "p2p_txn_value",
        label: "P2P Transfer Value",
        sortable: true,
        render: (w) => inlineValueCount(num(w.p2p_txn_value) || 0, num(w.p2p_txn_count) || 0, "text-cyan-400"),
      };

      const fundTransferCol: ColumnDef = {
        key: "fund_transfer_value",
        label: "Fund Transfer Value",
        sortable: true,
        render: (w) => inlineValueCount(num(w.fund_transfer_value) || 0, num(w.fund_transfer_count) || 0, "text-purple-400"),
      };

      const winRate: ColumnDef = {
        key: "win_rate",
        label: "Win%",
        sortable: true,
        render: (w) => {
          const wr = num(w.win_rate);
          if (wr == null) return <>—</>;
          return `${wr.toFixed(0)}%`;
        },
      };

      const pnl: ColumnDef = { key: "pnl", label: "PnL", sortable: true, render: (w) => signedCurrency(w.pnl, true) };
      const balance: ColumnDef = { key: "balance", label: "Balance", sortable: true, render: (w) => plainCurrency(w.balance) };
      const position: ColumnDef = {
        key: "position_value",
        label: "Open Position",
        sortable: true,
        render: (w) => plainCurrency(w.position_value),
      };

      const lastTraded: ColumnDef = {
        key: "last_trade_at",
        label: "Last Active",
        sortable: true,
        render: (w) => relativeDate(w.last_trade_at),
      };

      return [wallet, p2pTxnCol, fundTransferCol, winRate, pnl, balance, position, lastTraded];
    }

    if (isAnalyticsView) {
      const avgBuyPrice: ColumnDef = {
        key: "avg_buy_price",
        label: "Avg Buy",
        sortable: true,
        render: (w) => {
          const bp = num(w.avg_buy_price);
          return bp && bp > 0 ? formatPriceCents(bp) : "—";
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
        makeBucketCol("buys_below_15c", "<0.15", "text-foreground", "buys_below_15c", "wins_below_15c"),
        makeBucketCol("buys_15_30c", "0.15-0.30", "text-foreground", "buys_15_30c", "wins_15_30c"),
        makeBucketCol("buys_30_45c", "0.30-0.45", "text-foreground", "buys_30_45c", "wins_30_45c"),
        makeBucketCol("buys_45_60c", "0.45-0.60", "text-foreground", "buys_45_60c", "wins_45_60c"),
        makeBucketCol("buys_60_75c", "0.60-0.75", "text-foreground", "buys_60_75c", "wins_60_75c"),
        makeBucketCol("buys_above_75c", ">0.75", "text-foreground", "buys_above_75c", "wins_above_75c"),
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
        return `${wr.toFixed(0)}%`;
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
  }, [isAnalyticsView, isParlayView, isLineageView, tradeSortKey, tradeSortDir, copiedAddress, handleCopy, watchlistStatus, handleAddToWatchlist]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="w-full h-full flex flex-col bg-background">
      {/* Description only (Hibernated has no category row — otherwise the description shares that row) */}
      {isHibernated && (
        <p className="w-full text-right text-xs text-subtle flex-shrink-0 mb-3">{TAB_DESCRIPTIONS[tab]}</p>
      )}

      {/* Category tabs & Controls (Hidden for Hibernated) */}
      {!isHibernated && (
        <div className="flex flex-col gap-3 flex-shrink-0 border-b border-border w-full pb-3 mb-3">
          {/* Category tabs + description on one row */}
          <div className="flex items-end justify-between gap-4 flex-wrap">
            {!isLineageView ? (
              <div className="flex items-center gap-4 flex-wrap">
                {CATEGORY_TABS.map((cat) => (
                  <button
                    key={cat.key}
                    onClick={() => { setCategory(cat.key); resetAllPages(); setSortField("pnl"); setSortOrder("desc"); }}
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
            ) : (
              <div />
            )}
            <p className="text-xs text-subtle flex-shrink-0 pb-1">{TAB_DESCRIPTIONS[tab]}</p>
          </div>

          {/* Controls Bar: Sample Range + ViewDropdown beside it */}
          <div className="flex items-center justify-between gap-4 flex-wrap">
            {!isLineageView ? (
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
                        resetAllPages();
                      }
                    }}
                    className="w-36 accent-blue-500 cursor-pointer h-1.5 bg-surface-3 rounded-lg"
                  />
                  <span className="text-xs font-bold text-blue-400 min-w-[70px]">
                    {PNL_WINDOW_OPTIONS.find(opt => opt.value === pnlWindow)?.label || "Last 5000+"}
                  </span>
                </div>

                {/* Quick Snap Pills */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  {PNL_WINDOW_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => { 
                        setPnlWindow(opt.value);
                        resetAllPages(); 
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
            ) : (
              <div className="flex items-center gap-2 text-xs font-medium text-muted-fg">
                <span className="px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-semibold">
                  ⇄ Lineage & Transfers Mode
                </span>
                <span>Tracking wallet P2P position transfers & funding relationships</span>
              </div>
            )}

            {/* View Dropdown beside sample range */}
            <div className="ml-auto flex-shrink-0">
              <ViewDropdown
                value={currentViewMode}
                onChange={(mode) => {
                  setViewMode(mode);
                  if (mode === "parlay") {
                    setParlayPage(1);
                    setParlaySortField("parlay_pnl");
                    setParlaySortOrder("desc");
                  } else if (mode === "lineage") {
                    setLineagePage(1);
                    setLineageSortField("p2p_txn_value");
                    setLineageSortOrder("desc");
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Subcategory Pills + Search Row */}
      <div className="flex items-center justify-between flex-shrink-0 mb-2 gap-4">
        {!isHibernated && !isLineageView && subcategoryOptions.length > 0 ? (
          <div className="flex items-center gap-2 overflow-x-auto pb-1 flex-1 min-w-0 scrollbar-hide">
            <button
              onClick={() => { setFilterSubcategory(""); setFilterLeague(""); resetAllPages(); }}
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
                onClick={() => { setFilterSubcategory(sub); setFilterLeague(""); resetAllPages(); }}
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

        <div className="relative ml-auto flex-shrink-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-subtle" />
          <input
            type="text"
            placeholder="Search address or username..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              resetAllPages();
            }}
            className="pl-9 pr-4 py-1.5 text-xs bg-surface-2 border border-border rounded-xl text-foreground placeholder:text-subtle focus:outline-none focus:border-primary/50 w-64 transition-all"
          />
        </div>
      </div>

      {/* Tier 3: League Pills Row (appears when a subcategory is active and has leagues) */}
      {!isHibernated && !isLineageView && leagueOptions.length > 0 && (
        <div className="flex w-full items-center gap-1.5 overflow-x-auto pb-2 mb-3 flex-shrink-0 min-w-0 scrollbar-hide text-xs animate-in fade-in duration-200">
          <span className="text-[11px] font-bold text-muted-fg uppercase tracking-wider pl-1 pr-1.5 flex items-center gap-1">
            🏆 League:
          </span>
          <button
            onClick={() => { setFilterLeague(""); resetAllPages(); }}
            className={`px-2.5 py-0.5 text-xs font-semibold rounded-lg whitespace-nowrap transition-colors border ${
              filterLeague === ""
                ? "bg-blue-500/20 text-blue-400 border-blue-500/40 shadow-sm"
                : "bg-surface-2/70 text-muted-fg border-transparent hover:text-foreground hover:bg-surface-3"
            }`}
          >
            All {filterSubcategory || "Leagues"}
          </button>
          {leagueOptions.map((lg) => (
            <button
              key={lg}
              onClick={() => { setFilterLeague(lg); resetAllPages(); }}
              className={`px-2.5 py-0.5 text-xs font-semibold rounded-lg whitespace-nowrap transition-colors border ${
                filterLeague === lg
                  ? "bg-blue-500/20 text-blue-400 border-blue-500/40 shadow-sm"
                  : "bg-surface-2/70 text-muted-fg border-transparent hover:text-foreground hover:bg-surface-3"
              }`}
            >
              {lg}
            </button>
          ))}
        </div>
      )}

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
                  {isLineageView ? (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("p2p_txn_value")}>
                        <div className="flex items-center justify-end gap-1">P2P Transfer Value {activeSortField === "p2p_txn_value" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("fund_transfer_value")}>
                        <div className="flex items-center justify-end gap-1">Fund Transfer Value {activeSortField === "fund_transfer_value" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("win_rate")}>
                        <div className="flex items-center justify-end gap-1">Win% {activeSortField === "win_rate" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("pnl")}>
                        <div className="flex items-center justify-end gap-1">PnL {activeSortField === "pnl" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("balance")}>
                        <div className="flex items-center justify-end gap-1">Balance {activeSortField === "balance" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("position_value")}>
                        <div className="flex items-center justify-end gap-1">Open Position {activeSortField === "position_value" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                    </>
                  ) : isParlayView ? (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-center">Source</th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_win_rate")}>
                        <div className="flex items-center justify-end gap-1">Win% {activeSortField === "parlay_win_rate" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_winning_count")}>
                        <div className="flex items-center justify-end gap-1">Wins {activeSortField === "parlay_winning_count" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_resolved_count")}>
                        <div className="flex items-center justify-end gap-1">Resolved {activeSortField === "parlay_resolved_count" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_pnl")}>
                        <div className="flex items-center justify-end gap-1">Parlay PnL {activeSortField === "parlay_pnl" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_volume")}>
                        <div className="flex items-center justify-end gap-1">Parlay Vol {activeSortField === "parlay_volume" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("parlay_open_count")}>
                        <div className="flex items-center justify-end gap-1">Open Parlays {activeSortField === "parlay_open_count" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                    </>
                  ) : !isAnalyticsView ? (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-center">Source</th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("win_rate")}>
                        <div className="flex items-center justify-end gap-1">Win% {activeSortField === "win_rate" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("winning_count")}>
                        <div className="flex items-center justify-end gap-1">Wins {activeSortField === "winning_count" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("pnl")}>
                        <div className="flex items-center justify-end gap-1">PnL {activeSortField === "pnl" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("roi")}>
                        <div className="flex items-center justify-end gap-1">ROI {activeSortField === "roi" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("volume")}>
                        <div className="flex items-center justify-end gap-1">Volume {activeSortField === "volume" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("balance")}>
                        <div className="flex items-center justify-end gap-1">Balance {activeSortField === "balance" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("position_value")}>
                        <div className="flex items-center justify-end gap-1">Open Pos {activeSortField === "position_value" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("resolved_count")}>
                        <div className="flex items-center justify-end gap-1">Resolved {activeSortField === "resolved_count" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                    </>
                  ) : (
                    <>
                      <th className="py-2.5 px-4 font-semibold text-center">Source</th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("avg_buy_price")}>
                        <div className="flex items-center justify-end gap-1">Avg Buy {activeSortField === "avg_buy_price" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("win_rate")}>
                        <div className="flex items-center justify-end gap-1">WIN% {activeSortField === "win_rate" && (activeSortOrder === "desc" ? "↓" : "↑")}</div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_below_15c")}>
                        <div className="text-xs font-bold text-foreground">
                          &lt;0.15 {(tradeSortKey === "buys_below_15c" || tradeSortKey === "wins_below_15c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_15_30c")}>
                        <div className="text-xs font-bold text-foreground">
                          0.15-0.30 {(tradeSortKey === "buys_15_30c" || tradeSortKey === "wins_15_30c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_30_45c")}>
                        <div className="text-xs font-bold text-foreground">
                          0.30-0.45 {(tradeSortKey === "buys_30_45c" || tradeSortKey === "wins_30_45c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_45_60c")}>
                        <div className="text-xs font-bold text-foreground">
                          0.45-0.60 {(tradeSortKey === "buys_45_60c" || tradeSortKey === "wins_45_60c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_60_75c")}>
                        <div className="text-xs font-bold text-foreground">
                          0.60-0.75 {(tradeSortKey === "buys_60_75c" || tradeSortKey === "wins_60_75c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                      <th className="py-2 px-3 font-semibold text-center cursor-pointer hover:text-foreground select-none whitespace-nowrap" onClick={() => handleTradeSort("buys_above_75c")}>
                        <div className="text-xs font-bold text-foreground">
                          &gt;0.75 {(tradeSortKey === "buys_above_75c" || tradeSortKey === "wins_above_75c") ? (tradeSortDir === "desc" ? "↓" : "↑") : ""}
                        </div>
                        <div className="text-[10px] text-muted-fg font-normal">
                          W/R · Avg Sell
                        </div>
                      </th>
                    </>
                  )}
                  <th className="py-2.5 px-4 font-semibold text-right cursor-pointer hover:text-foreground select-none" onClick={() => handleSort("last_trade_at")}>
                    <div className="flex items-center justify-end gap-1">
                      Last Active {activeSortField === "last_trade_at" && (activeSortOrder === "desc" ? "↓" : "↑")}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {wallets.map((w, i) => {
                  const pnlVal = num(w.pnl);
                  const roiVal = num(w.roi_pct) || 0;
                  const rawTier = (w.tier || "").toUpperCase();
                  let badgeStyle = "bg-surface-2 text-foreground border-border";
                  let label = "Standard";
                  if (rawTier === "CURATED") {
                    badgeStyle = "bg-surface-2 text-foreground border-border font-bold";
                    label = "Curated";
                  } else if (rawTier === "LOW_BALANCE") {
                    badgeStyle = "bg-surface-2 text-muted-fg border-border";
                    label = "Low Balance";
                  } else if (rawTier === "NEW") {
                    badgeStyle = "bg-surface-2 text-muted-fg border-border";
                    label = "New";
                  } else if (rawTier === "DEAD") {
                    badgeStyle = "bg-surface-2 text-muted-fg border-border";
                    label = "Dead";
                  } else if (w.sources?.includes("custom")) {
                    badgeStyle = "bg-surface-2 text-muted-fg border-border";
                    label = "Custom";
                  }

                  const parlayPnl = num(w.parlay_pnl);

                  return (
                    <tr key={w.address} className="border-b border-border hover:bg-background/50 transition-colors">
                      <td className="py-2.5 px-4 text-center font-medium text-muted-fg">{(activePage - 1) * PAGE_SIZE + i + 1}</td>
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
                      {isLineageView ? (
                        <>
                          <td className="py-2.5 px-4 text-right font-mono whitespace-nowrap">
                            <span className="text-xs font-bold text-cyan-400">
                              {formatCurrency(num(w.p2p_txn_value) || 0)}
                            </span>
                            <span className="text-muted-fg text-xs mx-1">-</span>
                            <span className="text-xs text-muted-fg">
                              {num(w.p2p_txn_count) || 0} txns
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono whitespace-nowrap">
                            <span className="text-xs font-bold text-purple-400">
                              {formatCurrency(num(w.fund_transfer_value) || 0)}
                            </span>
                            <span className="text-muted-fg text-xs mx-1">-</span>
                            <span className="text-xs text-muted-fg">
                              {num(w.fund_transfer_count) || 0} txns
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">
                            {formatPercent(w.win_rate, 0)}
                          </td>
                          <td className={`py-2.5 px-4 text-right font-mono font-bold ${pnlVal == null ? "text-muted-fg" : (pnlVal >= 0 ? "text-green-500" : "text-red-500")}`}>
                            {pnlVal != null ? `${pnlVal > 0 ? "+" : ""}${formatCurrency(pnlVal)}` : "—"}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(num(w.balance) || 0)}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">{formatCurrency(num(w.position_value) || 0)}</td>
                        </>
                      ) : isParlayView ? (
                        <>
                          <td className="py-2.5 px-4 text-center">
                            <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
                              {label}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">
                            {w.parlay_win_rate != null ? `${Number(w.parlay_win_rate).toFixed(0)}%` : "—"}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono font-medium text-foreground">
                            {num(w.parlay_winning_count) || 0}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">
                            {num(w.parlay_resolved_count) || 0}
                          </td>
                          <td className={`py-2.5 px-4 text-right font-mono font-bold ${parlayPnl != null && parlayPnl >= 0 ? "text-green-500" : (parlayPnl != null ? "text-red-500" : "text-muted-fg")}`}>
                            {parlayPnl != null ? `${parlayPnl > 0 ? "+" : ""}${formatCurrency(parlayPnl)}` : "—"}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-muted-fg">
                            {num(w.parlay_volume) != null ? formatCurrency(Number(w.parlay_volume)) : "—"}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">
                            {(() => {
                              const count = num(w.parlay_open_count) || 0;
                              const val = num(w.parlay_open_value) || 0;
                              if (count === 0 && val === 0) return <span className="text-muted-fg">—</span>;
                              return (
                                <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                                  <span className="text-xs font-semibold text-foreground">
                                    {count} {count === 1 ? "bet" : "bets"}
                                  </span>
                                  <span className="text-[11px] text-muted-fg">
                                    ({formatCurrency(val)})
                                  </span>
                                </div>
                              );
                            })()}
                          </td>
                        </>
                      ) : !isAnalyticsView ? (
                        <>
                          <td className="py-2.5 px-4 text-center">
                            <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
                              {label}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">
                            {formatPercent(w.win_rate, 0)}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono">{num(w.winning_count) || 0}</td>
                          <td className={`py-2.5 px-4 text-right font-mono font-bold ${pnlVal == null ? "text-muted-fg" : (pnlVal >= 0 ? "text-green-500" : "text-red-500")}`}>
                            {pnlVal != null ? `${pnlVal > 0 ? "+" : ""}${formatCurrency(pnlVal)}` : "—"}
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
                          <td className="py-2.5 px-4 text-center">
                            <span className={`inline-block px-2 py-0.5 text-[11px] font-medium rounded border ${badgeStyle}`}>
                              {label}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-xs">
                            {formatPriceCents(w.avg_buy_price)}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-xs">
                            {formatPercent(w.win_rate, 0)}
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_below_15c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_below_15c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_below_15c)}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_15_30c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_15_30c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_15_30c)}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_30_45c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_30_45c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_30_45c)}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_45_60c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_45_60c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_45_60c)}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_60_75c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_60_75c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_60_75c)}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-center font-mono text-[11px] whitespace-nowrap">
                            <span className="text-foreground font-semibold">{num(w.wins_above_75c) || 0}</span>
                            <span className="text-muted-fg">/</span>
                            <span className="text-foreground">{num(w.buys_above_75c) || 0}</span>
                            <span className="text-muted-fg mx-1">·</span>
                            <span className="text-muted-fg text-[10px]">
                              {formatPriceCents(w.avg_sell_above_75c)}
                            </span>
                          </td>
                        </>
                      )}
                      <td className="py-2.5 px-4 text-right font-mono text-muted-fg text-xs">
                        {w.last_trade_at ? new Date(w.last_trade_at as string).toLocaleDateString() : "Never (New)"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pagination page={activePage} totalPages={totalPages} totalCount={total} onPageChange={activeSetPage} />

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
