"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ExternalLink,
  Copy,
  Check,
  Globe,
  RotateCw,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  GitFork,
  Link2,
  Box,
  Layers,
  Briefcase,
  History,
  Zap,
} from "lucide-react";
import {
  getWalletStats,
  getWalletCategories,
  getWalletTrades,
  getWalletPositions,
  getWalletClosedPositions,
  getWalletReconciliation,
  getWalletParlays,
  getWatchlistCounts,
  getWalletFunding,
  getWalletPositionTransfers,
} from "@/utils/api";
import { formatCurrency, formatAddress, timeAgo, formatPercent } from "@/utils/format";
import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";
import { LikeButton } from "@/components/ui/LikeButton";
import { SkeletonTableRows } from "@/components/Skeleton";
import { LineageFlowGraph } from "@/components/wallet/LineageFlowGraph";
import { TraderBetsMatrix, PriceBucketData } from "@/components/wallet/TraderBetsMatrix";
import { HistoricalProgressionChart, ProgressionWindowData } from "@/components/wallet/HistoricalProgressionChart";
import { KpiCardStrip } from "@/components/wallet/KpiCardStrip";
import { LiveTradeStreamPanel } from "@/components/wallet/LiveTradeStreamPanel";
import { WalletSideRail } from "@/components/wallet/WalletSideRail";

const TABLE_PAGE_SIZE = 10;

function num(v: string | number | null | undefined): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return isNaN(n) ? null : n;
}

function uniqCategories(arr: any[]): string[] {
  const cats = new Set<string>();
  let hasOtherOrEmpty = false;
  for (const p of arr) {
    const raw = (p.category || "").trim();
    if (!raw || raw.toUpperCase() === "OTHER") {
      hasOtherOrEmpty = true;
    } else {
      cats.add(raw.toUpperCase());
    }
  }
  const sorted = Array.from(cats).sort();
  if (hasOtherOrEmpty) {
    sorted.push("OTHER");
  }
  return sorted;
}

function signedCurrency(v: string | number | null | undefined, bold = false) {
  const n = num(v);
  if (n == null) return <>—</>;
  return (
    <span className={`${n >= 0 ? "text-green-600" : "text-red-500"} ${bold ? "font-bold" : ""}`}>
      {n > 0 ? "+" : ""}
      {formatCurrency(n)}
    </span>
  );
}

function getEffectiveClosedDate(cp: any): { dateStr: string; timestampMs: number } | null {
  if (!cp) return null;
  if (cp._effDate !== undefined) return cp._effDate;

  const ts = cp.timestamp ? Number(cp.timestamp) * (Number(cp.timestamp) < 1e11 ? 1000 : 1) : null;
  const closedAtTs = cp.closed_at || cp.closedAt ? new Date(cp.closed_at || cp.closedAt).getTime() : null;

  let redeemTs: number | null = null;
  if (ts && !isNaN(ts)) {
    redeemTs = ts;
  } else if (closedAtTs && !isNaN(closedAtTs)) {
    redeemTs = closedAtTs;
  }

  let expiryTs: number | null = null;
  if (cp.endDate || cp.end_date) {
    const d = new Date(cp.endDate || cp.end_date);
    if (!isNaN(d.getTime())) {
      expiryTs = d.getTime();
    }
  }

  let effectiveTs: number | null = null;
  if (redeemTs != null && expiryTs != null) {
    effectiveTs = Math.min(redeemTs, expiryTs);
  } else if (redeemTs != null) {
    effectiveTs = redeemTs;
  } else if (expiryTs != null) {
    effectiveTs = expiryTs;
  }

  if (effectiveTs == null) {
    cp._effDate = null;
    return null;
  }

  const dt = new Date(effectiveTs);
  const formatted = dt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  cp._effDate = { dateStr: formatted, timestampMs: effectiveTs };
  return cp._effDate;
}

function MarketTitleCell({
  title,
  conditionId,
  slug,
  eventSlug,
}: {
  title?: string;
  conditionId?: string;
  slug?: string;
  eventSlug?: string;
  asset?: string;
}) {
  const isMissing = !title || title === "—" || title.trim() === "";
  const displayTitle = isMissing
    ? conditionId
      ? `Market ${conditionId.slice(0, 10)}...`
      : "—"
    : title;
  const polySlug = (slug || eventSlug || "").trim();
  const isGeneric = isMissing || displayTitle.startsWith("Parlay (") || displayTitle.startsWith("Market 0x");
  const polyUrl = polySlug && polySlug !== "null" && polySlug !== "undefined" && polySlug !== ""
    ? `https://polymarket.com/event/${polySlug}`
    : !isGeneric
    ? `https://polymarket.com?_q=${encodeURIComponent(displayTitle)}`
    : conditionId
    ? `https://polymarket.com?_q=${encodeURIComponent(conditionId)}`
    : "";

  return (
    <div className="flex items-center gap-1.5 w-full min-w-0 group">
      {polyUrl ? (
        <a
          href={polyUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-foreground hover:text-primary transition-colors truncate hover:underline flex-1 min-w-0"
          title={displayTitle}
        >
          {displayTitle}
        </a>
      ) : (
        <span className="font-medium text-foreground truncate flex-1 min-w-0" title={displayTitle}>
          {displayTitle}
        </span>
      )}
      {polyUrl && (
        <a
          href={polyUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-fg/60 hover:text-primary flex-shrink-0 transition-colors p-0.5"
          title="Open in Polymarket"
        >
          <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

interface SortHeaderProps {
  label: string;
  sortKey: string;
  currentKey: string;
  currentDir: "asc" | "desc";
  onSort: (key: string) => void;
  align?: "left" | "center" | "right";
  className?: string;
}

function SortHeader({
  label,
  sortKey,
  currentKey,
  currentDir,
  onSort,
  align = "left",
  className = "",
}: SortHeaderProps) {
  const isActive = currentKey === sortKey;
  return (
    <th
      onClick={() => onSort(sortKey)}
      className={`py-2 px-3 font-semibold select-none cursor-pointer group transition-colors hover:text-foreground ${
        align === "center" ? "text-center" : align === "right" ? "text-right" : "text-left"
      } ${className}`}
    >
      <div
        className={`inline-flex items-center gap-1 ${
          align === "center" ? "justify-center" : align === "right" ? "justify-end" : "justify-start"
        }`}
      >
        <span>{label}</span>
        {isActive ? (
          currentDir === "asc" ? (
            <ArrowUp size={11} className="text-primary shrink-0" />
          ) : (
            <ArrowDown size={11} className="text-primary shrink-0" />
          )
        ) : (
          <ArrowUpDown size={10} className="opacity-0 group-hover:opacity-60 text-muted-fg transition-opacity shrink-0" />
        )}
      </div>
    </th>
  );
}

function CategoryFilterSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  if (!options.length) return null;
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-2 py-1 rounded-lg bg-surface border border-border text-[11px] font-semibold text-muted-fg hover:text-foreground cursor-pointer outline-none shadow-2xs hover:bg-surface-2 transition-colors"
      title="Filter by category"
    >
      <option value="">All Categories</option>
      {options.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

function CategoryScopeSelect({
  value,
  onChange,
}: {
  value: "root" | "all" | "positions" | "parlays";
  onChange: (v: "root" | "all" | "positions" | "parlays") => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as any)}
      className="px-2.5 py-1 rounded-lg bg-surface border border-border text-[11px] font-semibold text-foreground cursor-pointer outline-none shadow-2xs hover:bg-surface-2 transition-colors font-sans"
      title="Filter category scope"
    >
      <option value="root">Root Categories (Sums to 100%)</option>
      <option value="all">Detailed Breakdown (Leagues & Subs)</option>
      <option value="positions">Positions Only</option>
      <option value="parlays">Parlays Only</option>
    </select>
  );
}

function ClosedSubFilterSelect({
  value,
  onChange,
}: {
  value: "all" | "closed_only" | "concluded_only";
  onChange: (v: "all" | "closed_only" | "concluded_only") => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as "all" | "closed_only" | "concluded_only")}
      className="px-2.5 py-1 rounded-lg bg-surface border border-border text-[11px] font-semibold text-foreground cursor-pointer outline-none shadow-2xs hover:bg-surface-2 transition-colors font-sans"
      title="Filter position status"
    >
      <option value="all">All (Closed + Concluded)</option>
      <option value="closed_only">Only Closed (Redeemed/Sold)</option>
      <option value="concluded_only">Open but Concluded</option>
    </select>
  );
}

function ClosedOutcomeFilterSelect({
  value,
  onChange,
}: {
  value: "all" | "won" | "lost";
  onChange: (v: "all" | "won" | "lost") => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as "all" | "won" | "lost")}
      className="px-2.5 py-1 rounded-lg bg-surface border border-border text-[11px] font-semibold text-foreground cursor-pointer outline-none shadow-2xs hover:bg-surface-2 transition-colors font-sans"
      title="Filter by win/loss result"
    >
      <option value="all">All Outcomes (Won & Lost)</option>
      <option value="won">Won Only</option>
      <option value="lost">Lost Only</option>
    </select>
  );
}

function PaginationFooter({
  page,
  pageCount,
  total,
  onPage,
}: {
  page: number;
  pageCount: number;
  total: number;
  onPage: (p: number) => void;
}) {
  return (
    <div className="px-3 py-2 border-t border-border bg-surface-2/40 flex items-center justify-between flex-shrink-0">
      <span className="text-[10px] text-muted-fg font-mono">{total} total</span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPage(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface border border-border hover:bg-surface-2 text-muted-fg hover:text-foreground transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ← Prev
        </button>
        <span className="text-[10px] text-muted-fg font-mono">
          Page {page} of {pageCount}
        </span>
        <button
          onClick={() => onPage(Math.min(pageCount, page + 1))}
          disabled={page >= pageCount}
          className="px-2 py-0.5 rounded text-[10px] font-semibold bg-surface border border-border hover:bg-surface-2 text-muted-fg hover:text-foreground transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

function aggregateCategoryBreakdown(items: any[]) {
  const map = new Map<string, {
    category: string;
    subcategory: string;
    league: string;
    resolved_count: number;
    winning_count: number;
    losing_count: number;
    pnl: number;
    volume: number;
  }>();

  for (const item of items) {
    const rawCat = (item.category || "OTHER").trim().toUpperCase();
    const cat = rawCat || "OTHER";
    let subcat = (item.subcategory || "").trim();
    if (
      subcat.toUpperCase() === cat ||
      subcat.toUpperCase() === "GENERAL" ||
      subcat.toUpperCase() === "OTHER" ||
      subcat.toUpperCase() === "SPORTS"
    ) {
      subcat = "";
    }
    const league = (item.league || "").trim();
    const pnl = num(item.realizedPnl ?? item.realized_pnl ?? item.cashPnl ?? item.pnl) || 0;
    const vol = num(item.totalBought ?? item.total_bought ?? item.entryCost ?? item.size) || 0;
    const isWin = pnl > 0 || ((num(item.avgSellPrice ?? item.avg_sell_price ?? item.curPrice) ?? 0) >= 0.95);

    // 1. Root Category Roll-up row: (cat, "", "")
    const rootKey = `${cat}||`;
    if (!map.has(rootKey)) {
      map.set(rootKey, { category: cat, subcategory: "", league: "", resolved_count: 0, winning_count: 0, losing_count: 0, pnl: 0, volume: 0 });
    }
    const root = map.get(rootKey)!;
    root.resolved_count += 1;
    if (isWin) root.winning_count += 1;
    else root.losing_count += 1;
    root.pnl += pnl;
    root.volume += vol;

    // 2. Specific Subcategory / League breakdown row: (cat, subcat, league)
    if (subcat || league) {
      const subKey = `${cat}|${subcat}|${league}`;
      if (!map.has(subKey)) {
        map.set(subKey, { category: cat, subcategory: subcat, league: league, resolved_count: 0, winning_count: 0, losing_count: 0, pnl: 0, volume: 0 });
      }
      const sub = map.get(subKey)!;
      sub.resolved_count += 1;
      if (isWin) sub.winning_count += 1;
      else sub.losing_count += 1;
      sub.pnl += pnl;
      sub.volume += vol;
    }
  }

  return Array.from(map.values()).map((r) => ({
    ...r,
    win_rate: r.resolved_count > 0 ? (r.winning_count / r.resolved_count) * 100 : 0,
    roi_pct: r.volume >= 10 ? (r.pnl / r.volume) * 100 : 0,
  }));
}

export default function WalletProfilePage() {
  const params = useParams();
  const address = (params?.address as string)?.toLowerCase();

  const { isLiked, toggleLike } = useFavoriteToggle(address ? [address] : []);
  const [favoriteCount, setFavoriteCount] = useState<number>(0);

  const [stats, setStats] = useState<any>(null);
  const [funding, setFunding] = useState<any>(null);
  const [positionTransfers, setPositionTransfers] = useState<any>(null);
  const [categories, setCategories] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [closedPositions, setClosedPositions] = useState<any[]>([]);
  const [reconciliation, setReconciliation] = useState<any>(null);
  const [openParlays, setOpenParlays] = useState<any[]>([]);
  const [closedParlays, setClosedParlays] = useState<any[]>([]);

  // Unified Tab state: positions plus the source-integrity review tab.
  const [activeTab, setActiveTab] = useState<
    "open" | "closed" | "open_parlay" | "closed_parlay" | "categories" | "integrity"
  >("categories");

  // Category Scope state: "root" | "all" | "positions" | "parlays"
  const [categoryScope, setCategoryScope] = useState<"root" | "all" | "positions" | "parlays">("root");

  // Sorting states
  const [openPositionsSort, setOpenPositionsSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "invested", dir: "desc" });
  const [closedPositionsSort, setClosedPositionsSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "date", dir: "desc" });
  const [openParlaysSort, setOpenParlaysSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "invested", dir: "desc" });
  const [closedParlaysSort, setClosedParlaysSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "pnl", dir: "desc" });
  const [categoriesSort, setCategoriesSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "pnl", dir: "desc" });

  // Filter + pagination states
  const [openPositionsCategoryFilter, setOpenPositionsCategoryFilter] = useState("");
  const [closedPositionsCategoryFilter, setClosedPositionsCategoryFilter] = useState("");
  const [closedPositionsSubFilter, setClosedPositionsSubFilter] = useState<"all" | "closed_only" | "concluded_only">("all");
  const [closedPositionsOutcomeFilter, setClosedPositionsOutcomeFilter] = useState<"all" | "won" | "lost">("all");
  const [openParlaysCategoryFilter, setOpenParlaysCategoryFilter] = useState("");
  const [closedParlaysCategoryFilter, setClosedParlaysCategoryFilter] = useState("");
  const [categoriesCategoryFilter, setCategoriesCategoryFilter] = useState("");

  const [openPositionsPage, setOpenPositionsPage] = useState(1);
  const [closedPositionsPage, setClosedPositionsPage] = useState(1);
  const [openParlaysPage, setOpenParlaysPage] = useState(1);
  const [closedParlaysPage, setClosedParlaysPage] = useState(1);
  const [categoriesPage, setCategoriesPage] = useState(1);

  const handleSort = (setter: React.Dispatch<React.SetStateAction<{ key: string; dir: "asc" | "desc" }>>) => (key: string) => {
    setter((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "desc" ? "asc" : "desc",
    }));
  };

  const currentAddressRef = useRef(address);
  const loadedTabsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    currentAddressRef.current = address;
  }, [address]);

  const [statsLoading, setStatsLoading] = useState(true);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [openPositionsLoading, setOpenPositionsLoading] = useState(false);
  const [closedPositionsLoading, setClosedPositionsLoading] = useState(false);
  const [parlaysLoading, setParlaysLoading] = useState(false);
  const [tradesLoading, setTradesLoading] = useState(false);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [reconciliationLoading, setReconciliationLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [copied, setCopied] = useState(false);

  // 1. Stats Loader (Header, Overview, KPIs - Priority 1)
  const loadStats = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setStatsLoading(true);
    try {
      const s = await getWalletStats(targetAddr).catch(() => null);
      if (currentAddressRef.current === targetAddr) {
        setStats(s);
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setStatsLoading(false);
      }
    }
  };

  // 2. Categories Loader (Priority 2 - On Demand)
  const loadCategories = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setCategoriesLoading(true);
    try {
      const c = await getWalletCategories(targetAddr).catch(() => []);
      if (currentAddressRef.current === targetAddr) {
        setCategories(Array.isArray(c) ? c : []);
        loadedTabsRef.current.add("categories");
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setCategoriesLoading(false);
      }
    }
  };

  // 3. Open Positions Loader (Priority 2 - On Demand)
  const loadOpenPositions = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setOpenPositionsLoading(true);
    try {
      const p = await getWalletPositions(targetAddr).catch(() => []);
      if (currentAddressRef.current === targetAddr) {
        setPositions(Array.isArray(p) ? p : []);
        loadedTabsRef.current.add("open");
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setOpenPositionsLoading(false);
      }
    }
  };

  // 4. Closed Positions Loader (Priority 2 - On Demand)
  const loadClosedPositions = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setClosedPositionsLoading(true);
    try {
      const cp = await getWalletClosedPositions(targetAddr).catch(() => []);
      if (currentAddressRef.current === targetAddr) {
        setClosedPositions(Array.isArray(cp) ? cp : []);
        loadedTabsRef.current.add("closed");
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setClosedPositionsLoading(false);
      }
    }
  };

  const loadReconciliation = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setReconciliationLoading(true);
    try {
      const data = await getWalletReconciliation(targetAddr).catch(() => null);
      if (currentAddressRef.current === targetAddr) {
        setReconciliation(data);
        loadedTabsRef.current.add("integrity");
      }
    } finally {
      if (currentAddressRef.current === targetAddr) setReconciliationLoading(false);
    }
  };

  // 5. Parlays Loader (Priority 2 - On Demand)
  const loadParlays = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setParlaysLoading(true);
    try {
      const parlays = await getWalletParlays(targetAddr).catch(() => null);
      if (currentAddressRef.current === targetAddr) {
        let finalOpen = Array.isArray(parlays?.open_parlays) ? parlays.open_parlays : [];
        let finalClosed = Array.isArray(parlays?.closed_parlays) ? parlays.closed_parlays : [];
        setOpenParlays(finalOpen);
        setClosedParlays(finalClosed);
        loadedTabsRef.current.add("parlays");
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setParlaysLoading(false);
      }
    }
  };

  // 6. Trades Stream Loader (Background)
  const loadTrades = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setTradesLoading(true);
    try {
      const t = await getWalletTrades(targetAddr).catch(() => []);
      if (currentAddressRef.current === targetAddr) {
        setTrades(Array.isArray(t) ? t : []);
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setTradesLoading(false);
      }
    }
  };

  // 7. Funding & Lineage Loader (Background)
  const loadLineage = async (targetAddr: string = address) => {
    if (!targetAddr) return;
    setLineageLoading(true);
    try {
      const [wCount, fund, pTrans] = await Promise.all([
        getWatchlistCounts([targetAddr]).catch(() => null),
        getWalletFunding(targetAddr).catch(() => null),
        getWalletPositionTransfers(targetAddr, 50).catch(() => null),
      ]);
      if (currentAddressRef.current === targetAddr) {
        setFunding(fund);
        setPositionTransfers(pTrans);
        if (wCount?.counts && wCount.counts[targetAddr] != null) {
          setFavoriteCount(wCount.counts[targetAddr]);
        }
      }
    } finally {
      if (currentAddressRef.current === targetAddr) {
        setLineageLoading(false);
      }
    }
  };

  // Switch tab with progressive lazy fetching
  const switchActiveTab = (tab: "open" | "closed" | "open_parlay" | "closed_parlay" | "categories" | "integrity") => {
    setActiveTab(tab);
    if (!address) return;
    if (tab === "categories" && !loadedTabsRef.current.has("categories")) {
      loadCategories(address);
    } else if (tab === "open" && !loadedTabsRef.current.has("open")) {
      loadOpenPositions(address);
    } else if (tab === "closed" && !loadedTabsRef.current.has("closed")) {
      loadClosedPositions(address);
    } else if ((tab === "open_parlay" || tab === "closed_parlay") && !loadedTabsRef.current.has("parlays")) {
      loadParlays(address);
    } else if (tab === "integrity" && !loadedTabsRef.current.has("integrity")) {
      loadReconciliation(address);
    }
  };

  // Progressive initial mount
  useEffect(() => {
    if (!address) return;
    loadedTabsRef.current.clear();
    setStats(null);
    setCategories([]);
    setPositions([]);
    setClosedPositions([]);
    setReconciliation(null);
    setOpenParlays([]);
    setClosedParlays([]);
    setFunding(null);
    setPositionTransfers(null);

    // Step 1: Immediate Header & Stats
    loadStats(address);

    // Step 2: Load Active Default Tab
    if (activeTab === "categories") {
      loadCategories(address);
    } else if (activeTab === "open") {
      loadOpenPositions(address);
    } else if (activeTab === "closed") {
      loadClosedPositions(address);
    } else if (activeTab === "open_parlay" || activeTab === "closed_parlay") {
      loadParlays(address);
    } else if (activeTab === "integrity") {
      loadReconciliation(address);
    }

    // Step 3: Progressive Background Load (Loads Open/Closed Positions, Parlays, Lineage, and Trades for immediate tab counts!)
    const timer = setTimeout(() => {
      loadLineage(address);
      loadTrades(address);
      loadParlays(address);
      loadOpenPositions(address);
      loadClosedPositions(address);
      loadReconciliation(address);
    }, 50);

    return () => clearTimeout(timer);
  }, [address]);

  const loadData = async (showRefreshing = false) => {
    const targetAddr = address;
    if (!targetAddr) return;
    if (showRefreshing) {
      setRefreshing(true);
      loadedTabsRef.current.clear();
    }
    await loadStats(targetAddr);
    if (activeTab === "categories") await loadCategories(targetAddr);
    else if (activeTab === "open") await loadOpenPositions(targetAddr);
    else if (activeTab === "closed") await loadClosedPositions(targetAddr);
    else if (activeTab === "open_parlay" || activeTab === "closed_parlay") await loadParlays(targetAddr);
    else if (activeTab === "integrity") await loadReconciliation(targetAddr);

    loadLineage(targetAddr);
    loadTrades(targetAddr);
    setRefreshing(false);
  };

  const handleToggleFavorite = (e: React.MouseEvent) => {
    const currentlyLiked = isLiked(address);
    setFavoriteCount((prev) => (currentlyLiked ? Math.max(0, prev - 1) : prev + 1));
    toggleLike(address, e);
  };

  const copyAddress = () => {
    if (!address) return;
    navigator.clipboard.writeText(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // 1. Sorted + filtered Live Open Positions
  const sortedPositions = useMemo(() => {
    let arr = positions;
    if (openPositionsCategoryFilter) {
      const f = openPositionsCategoryFilter.toUpperCase();
      arr = arr.filter((p) => (p.category || "OTHER").toUpperCase() === f);
    }
    if (arr.length <= 1) return arr;

    const { key, dir } = openPositionsSort;
    const isAsc = dir === "asc";

    if (key === "pnl") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.cashPnl ?? a.cash_pnl ?? a.unrealizedPnl ?? a.pnl ?? 0) || 0;
        const pB = Number(b.cashPnl ?? b.cash_pnl ?? b.unrealizedPnl ?? b.pnl ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }
    if (key === "currentValue") {
      return [...arr].sort((a, b) => {
        const vA = Number(a.currentValue ?? a.current_value ?? 0) || 0;
        const vB = Number(b.currentValue ?? b.current_value ?? 0) || 0;
        return isAsc ? vA - vB : vB - vA;
      });
    }
    if (key === "invested") {
      return [...arr].sort((a, b) => {
        const tA = Number(a.totalBought ?? a.size ?? a.tokens ?? 0) || 0;
        const pA = Number(a.avgPrice ?? a.avg_price ?? 0) || 0;
        const iA = tA > 0 && pA > 0 ? tA * pA : Math.max(0, (Number(a.currentValue) || 0) - (Number(a.cashPnl) || 0));

        const tB = Number(b.totalBought ?? b.size ?? b.tokens ?? 0) || 0;
        const pB = Number(b.avgPrice ?? b.avg_price ?? 0) || 0;
        const iB = tB > 0 && pB > 0 ? tB * pB : Math.max(0, (Number(b.currentValue) || 0) - (Number(b.cashPnl) || 0));

        return isAsc ? iA - iB : iB - iA;
      });
    }
    if (key === "tokens") {
      return [...arr].sort((a, b) => {
        const tA = Number(a.totalBought ?? a.size ?? a.tokens ?? 0) || 0;
        const tB = Number(b.totalBought ?? b.size ?? b.tokens ?? 0) || 0;
        return isAsc ? tA - tB : tB - tA;
      });
    }
    if (key === "avgEntry") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.avgPrice ?? a.avg_price ?? 0) || 0;
        const pB = Number(b.avgPrice ?? b.avg_price ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }
    if (key === "date") {
      const getTs = (p: any): number => {
        const raw = p.entryAt ?? p.entry_at ?? p.timestamp;
        if (raw == null) return 0;
        if (typeof raw === "number") return raw > 1e12 ? raw : raw * 1000;
        const ms = new Date(raw).getTime();
        return isNaN(ms) ? 0 : ms;
      };
      return [...arr].sort((a, b) => {
        const dA = a._ts ?? (a._ts = getTs(a));
        const dB = b._ts ?? (b._ts = getTs(b));
        return isAsc ? dA - dB : dB - dA;
      });
    }
    if (key === "market") {
      return [...arr].sort((a, b) => {
        const tA = (a.title || a.market_title || "").toLowerCase();
        const tB = (b.title || b.market_title || "").toLowerCase();
        return isAsc ? tA.localeCompare(tB) : tB.localeCompare(tA);
      });
    }
    if (key === "outcome") {
      return [...arr].sort((a, b) => {
        const oA = (a.side || a.outcome || "").toUpperCase();
        const oB = (b.side || b.outcome || "").toUpperCase();
        return isAsc ? oA.localeCompare(oB) : oB.localeCompare(oA);
      });
    }
    return arr;
  }, [positions, openPositionsSort, openPositionsCategoryFilter]);

  const openPositionsPageCount = Math.max(1, Math.ceil(sortedPositions.length / TABLE_PAGE_SIZE));
  const pagedOpenPositions = useMemo(
    () =>
      sortedPositions.slice(
        (Math.min(openPositionsPage, openPositionsPageCount) - 1) * TABLE_PAGE_SIZE,
        Math.min(openPositionsPage, openPositionsPageCount) * TABLE_PAGE_SIZE
      ),
    [sortedPositions, openPositionsPage, openPositionsPageCount]
  );

  // 2. Sorted + filtered Closed Positions (High-Speed O(N) sort)
  const sortedClosedPositions = useMemo(() => {
    let arr = closedPositions;
    if (closedPositionsCategoryFilter) {
      const f = closedPositionsCategoryFilter.toUpperCase();
      arr = arr.filter((p) => (p.category || "OTHER").toUpperCase() === f);
    }
    if (closedPositionsSubFilter === "closed_only") {
      arr = arr.filter((p: any) => !p.isRedeemable && !p.is_redeemable);
    } else if (closedPositionsSubFilter === "concluded_only") {
      arr = arr.filter((p: any) => p.isRedeemable || p.is_redeemable);
    }
    if (closedPositionsOutcomeFilter === "won") {
      arr = arr.filter((p: any) => {
        const winningOutcome = p.winning_outcome || p.winningOutcome;
        if (winningOutcome) {
          return (p.outcome || p.side) === winningOutcome;
        }
        const pnl = Number(p.realizedPnl ?? p.realized_pnl ?? p.cashPnl ?? p.pnl ?? 0);
        const sellP = Number(p.avgSellPrice ?? p.avg_sell_price ?? p.curPrice ?? 0);
        return pnl > 0 || sellP >= 0.95;
      });
    } else if (closedPositionsOutcomeFilter === "lost") {
      arr = arr.filter((p: any) => {
        const winningOutcome = p.winning_outcome || p.winningOutcome;
        if (winningOutcome) {
          return (p.outcome || p.side) !== winningOutcome;
        }
        const pnl = Number(p.realizedPnl ?? p.realized_pnl ?? p.cashPnl ?? p.pnl ?? 0);
        const sellP = Number(p.avgSellPrice ?? p.avg_sell_price ?? p.curPrice ?? 0);
        return !(pnl > 0 || sellP >= 0.95);
      });
    }
    if (arr.length <= 1) return arr;

    const { key, dir } = closedPositionsSort;
    const isAsc = dir === "asc";

    if (key === "pnl") {
      return [...arr].sort((a, b) => {
        const valA = a.realizedPnl ?? a.realized_pnl ?? a.cashPnl ?? a.pnl ?? 0;
        const valB = b.realizedPnl ?? b.realized_pnl ?? b.cashPnl ?? b.pnl ?? 0;
        const nA = typeof valA === "number" ? valA : parseFloat(valA) || 0;
        const nB = typeof valB === "number" ? valB : parseFloat(valB) || 0;
        return isAsc ? nA - nB : nB - nA;
      });
    }

    if (key === "date") {
      return [...arr].sort((a, b) => {
        const dA = a._ts ?? (a._ts = getEffectiveClosedDate(a)?.timestampMs ?? 0);
        const dB = b._ts ?? (b._ts = getEffectiveClosedDate(b)?.timestampMs ?? 0);
        return isAsc ? dA - dB : dB - dA;
      });
    }

    if (key === "tokens") {
      return [...arr].sort((a, b) => {
        const tA = Number(a.totalBought ?? a.total_bought ?? a.size ?? 0) || 0;
        const tB = Number(b.totalBought ?? b.total_bought ?? b.size ?? 0) || 0;
        return isAsc ? tA - tB : tB - tA;
      });
    }

    if (key === "avgEntry") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.avgPrice ?? a.avg_price ?? a.avgBuyPrice ?? 0) || 0;
        const pB = Number(b.avgPrice ?? b.avg_price ?? b.avgBuyPrice ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }

    if (key === "invested") {
      return [...arr].sort((a, b) => {
        const iA = a.invested != null ? Number(a.invested) : (Number(a.totalBought ?? 0) * Number(a.avgPrice ?? 0)) || 0;
        const iB = b.invested != null ? Number(b.invested) : (Number(b.totalBought ?? 0) * Number(b.avgPrice ?? 0)) || 0;
        return isAsc ? iA - iB : iB - iA;
      });
    }

    if (key === "market") {
      return [...arr].sort((a, b) => {
        const tA = (a.title || a.market_title || "").toLowerCase();
        const tB = (b.title || b.market_title || "").toLowerCase();
        return isAsc ? tA.localeCompare(tB) : tB.localeCompare(tA);
      });
    }

    if (key === "outcome") {
      return [...arr].sort((a, b) => {
        const oA = (a.outcome || a.side || "").toUpperCase();
        const oB = (b.outcome || b.side || "").toUpperCase();
        return isAsc ? oA.localeCompare(oB) : oB.localeCompare(oA);
      });
    }

    return arr;
  }, [closedPositions, closedPositionsSort, closedPositionsCategoryFilter, closedPositionsSubFilter, closedPositionsOutcomeFilter]);

  const closedPositionsPageCount = Math.max(1, Math.ceil(sortedClosedPositions.length / TABLE_PAGE_SIZE));
  const pagedClosedPositions = useMemo(
    () =>
      sortedClosedPositions.slice(
        (Math.min(closedPositionsPage, closedPositionsPageCount) - 1) * TABLE_PAGE_SIZE,
        Math.min(closedPositionsPage, closedPositionsPageCount) * TABLE_PAGE_SIZE
      ),
    [sortedClosedPositions, closedPositionsPage, closedPositionsPageCount]
  );

  // 3. Sorted + filtered Open Parlays
  const sortedOpenParlays = useMemo(() => {
    let arr = openParlays;
    if (openParlaysCategoryFilter) {
      const f = openParlaysCategoryFilter.toUpperCase();
      arr = arr.filter((p) => (p.category || "OTHER").toUpperCase() === f);
    }
    if (arr.length <= 1) return arr;

    const { key, dir } = openParlaysSort;
    const isAsc = dir === "asc";

    if (key === "pnl") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.cashPnl ?? a.cash_pnl ?? a.unrealizedPnl ?? a.pnl ?? 0) || 0;
        const pB = Number(b.cashPnl ?? b.cash_pnl ?? b.unrealizedPnl ?? b.pnl ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }
    if (key === "currentValue") {
      return [...arr].sort((a, b) => {
        const vA = Number(a.currentValue ?? a.current_value ?? 0) || 0;
        const vB = Number(b.currentValue ?? b.current_value ?? 0) || 0;
        return isAsc ? vA - vB : vB - vA;
      });
    }
    if (key === "invested") {
      return [...arr].sort((a, b) => {
        const iA = Number(a.invested ?? a.entryCost ?? a.entry_cost ?? 0) || 0;
        const iB = Number(b.invested ?? b.entryCost ?? b.entry_cost ?? 0) || 0;
        return isAsc ? iA - iB : iB - iA;
      });
    }
    if (key === "tokens") {
      return [...arr].sort((a, b) => {
        const tA = Number(a.tokens ?? a.size ?? a.totalBought ?? 0) || 0;
        const tB = Number(b.tokens ?? b.size ?? b.totalBought ?? 0) || 0;
        return isAsc ? tA - tB : tB - tA;
      });
    }
    if (key === "avgEntry") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.avgPrice ?? a.avg_price ?? 0) || 0;
        const pB = Number(b.avgPrice ?? b.avg_price ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }
    if (key === "date") {
      const getTs = (p: any): number => {
        const raw = p.entryAt ?? p.entry_at ?? p.timestamp;
        if (raw == null) return 0;
        if (typeof raw === "number") return raw > 1e12 ? raw : raw * 1000;
        const ms = new Date(raw).getTime();
        return isNaN(ms) ? 0 : ms;
      };
      return [...arr].sort((a, b) => {
        const dA = a._ts ?? (a._ts = getTs(a));
        const dB = b._ts ?? (b._ts = getTs(b));
        return isAsc ? dA - dB : dB - dA;
      });
    }
    if (key === "market") {
      return [...arr].sort((a, b) => {
        const tA = (a.title || a.market_title || "").toLowerCase();
        const tB = (b.title || b.market_title || "").toLowerCase();
        return isAsc ? tA.localeCompare(tB) : tB.localeCompare(tA);
      });
    }
    if (key === "side") {
      return [...arr].sort((a, b) => {
        const sA = (a.side || a.outcome || "").toUpperCase();
        const sB = (b.side || b.outcome || "").toUpperCase();
        return isAsc ? sA - sB : sB - sA;
      });
    }
    return arr;
  }, [openParlays, openParlaysSort, openParlaysCategoryFilter]);

  const openParlaysPageCount = Math.max(1, Math.ceil(sortedOpenParlays.length / TABLE_PAGE_SIZE));
  const pagedOpenParlays = useMemo(
    () =>
      sortedOpenParlays.slice(
        (Math.min(openParlaysPage, openParlaysPageCount) - 1) * TABLE_PAGE_SIZE,
        Math.min(openParlaysPage, openParlaysPageCount) * TABLE_PAGE_SIZE
      ),
    [sortedOpenParlays, openParlaysPage, openParlaysPageCount]
  );

  // 4. Sorted + filtered Closed Parlays
  const sortedClosedParlays = useMemo(() => {
    let arr = closedParlays;
    if (closedParlaysCategoryFilter) {
      const f = closedParlaysCategoryFilter.toUpperCase();
      arr = arr.filter((p) => (p.category || "OTHER").toUpperCase() === f);
    }
    if (arr.length <= 1) return arr;

    const { key, dir } = closedParlaysSort;
    const isAsc = dir === "asc";

    if (key === "pnl") {
      return [...arr].sort((a, b) => {
        const rA = Number(a.realizedPnl ?? a.realized_pnl ?? a.cashPnl ?? a.pnl ?? 0) || 0;
        const rB = Number(b.realizedPnl ?? b.realized_pnl ?? b.cashPnl ?? b.pnl ?? 0) || 0;
        return isAsc ? rA - rB : rB - rA;
      });
    }
    if (key === "tokens") {
      return [...arr].sort((a, b) => {
        const tA = Number(a.tokens ?? a.size ?? a.totalBought ?? 0) || 0;
        const tB = Number(b.tokens ?? b.size ?? b.totalBought ?? 0) || 0;
        return isAsc ? tA - tB : tB - tA;
      });
    }
    if (key === "avgEntry") {
      return [...arr].sort((a, b) => {
        const pA = Number(a.avgPrice ?? a.avg_price ?? 0) || 0;
        const pB = Number(b.avgPrice ?? b.avg_price ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      });
    }
    if (key === "invested") {
      return [...arr].sort((a, b) => {
        const iA = Number(a.invested ?? a.entryCost ?? a.entry_cost ?? 0) || 0;
        const iB = Number(b.invested ?? b.entryCost ?? b.entry_cost ?? 0) || 0;
        return isAsc ? iA - iB : iB - iA;
      });
    }
    if (key === "market") {
      return [...arr].sort((a, b) => {
        const tA = (a.title || a.market_title || "").toLowerCase();
        const tB = (b.title || b.market_title || "").toLowerCase();
        return isAsc ? tA.localeCompare(tB) : tB.localeCompare(tA);
      });
    }
    if (key === "result") {
      return [...arr].sort((a, b) => {
        const rA = Number(a.realizedPnl ?? a.realized_pnl ?? 0) || 0;
        const rB = Number(b.realizedPnl ?? b.realized_pnl ?? 0) || 0;
        return isAsc ? (rA > 0 ? 1 : -1) - (rB > 0 ? 1 : -1) : (rB > 0 ? 1 : -1) - (rA > 0 ? 1 : -1);
      });
    }
    return arr;
  }, [closedParlays, closedParlaysSort, closedParlaysCategoryFilter]);

  const closedParlaysPageCount = Math.max(1, Math.ceil(sortedClosedParlays.length / TABLE_PAGE_SIZE));
  const pagedClosedParlays = useMemo(
    () =>
      sortedClosedParlays.slice(
        (Math.min(closedParlaysPage, closedParlaysPageCount) - 1) * TABLE_PAGE_SIZE,
        Math.min(closedParlaysPage, closedParlaysPageCount) * TABLE_PAGE_SIZE
      ),
    [sortedClosedParlays, closedParlaysPage, closedParlaysPageCount]
  );

  // 5. Active category breakdown list based on scope (Root Categories, Detailed Breakdown, Positions, Parlays)
  const activeCategoriesList = useMemo(() => {
    if (categoryScope === "root") {
      return (categories || []).filter(
        (r) => (r.category || "").toUpperCase() !== "OVERALL" && !r.subcategory && !r.league
      );
    }
    if (categoryScope === "all") {
      return (categories || []).filter(
        (r) => (r.category || "").toUpperCase() !== "OVERALL"
      );
    }
    if (categoryScope === "positions") {
      const posOnly = closedPositions.filter((p: any) => !p.is_parlay && !p.isParlay);
      return aggregateCategoryBreakdown(posOnly);
    }
    if (categoryScope === "parlays") {
      const parlayOnly = closedParlays.length > 0 ? closedParlays : closedPositions.filter((p: any) => p.is_parlay || p.isParlay);
      return aggregateCategoryBreakdown(parlayOnly);
    }
    return categories || [];
  }, [categoryScope, categories, closedPositions, closedParlays]);

  // 6. Sorted + paged Categories
  const sortedCategories = useMemo(() => {
    let arr = activeCategoriesList;
    if (categoriesCategoryFilter) {
      const f = categoriesCategoryFilter.toUpperCase();
      arr = arr.filter((c) => (c.category || "OTHER").toUpperCase() === f);
    }
    if (arr.length <= 1) return arr;
    const { key, dir } = categoriesSort;
    const isAsc = dir === "asc";

    return [...arr].sort((a, b) => {
      if (key === "pnl") {
        const pA = Number(a.pnl ?? 0) || 0;
        const pB = Number(b.pnl ?? 0) || 0;
        return isAsc ? pA - pB : pB - pA;
      }
      if (key === "winRate") {
        const wA = Number(a.win_rate ?? 0) || 0;
        const wB = Number(b.win_rate ?? 0) || 0;
        return isAsc ? wA - wB : wB - wA;
      }
      if (key === "volume") {
        const vA = Number(a.volume ?? 0) || 0;
        const vB = Number(b.volume ?? 0) || 0;
        return isAsc ? vA - vB : vB - vA;
      }
      if (key === "roi") {
        const rA = Number(a.roi_pct ?? 0) || 0;
        const rB = Number(b.roi_pct ?? 0) || 0;
        return isAsc ? rA - rB : rB - rA;
      }
      if (key === "resolved") {
        const rA = Number(a.resolved_count ?? (a.winning_count || 0) + (a.losing_count || 0)) || 0;
        const rB = Number(b.resolved_count ?? (b.winning_count || 0) + (b.losing_count || 0)) || 0;
        return isAsc ? rA - rB : rB - rA;
      }
      if (key === "category") {
        const cA = (a.category || "").toLowerCase();
        const cB = (b.category || "").toLowerCase();
        return isAsc ? cA.localeCompare(cB) : cB.localeCompare(cA);
      }
      if (key === "subcategory") {
        const sA = (a.subcategory || "").toLowerCase();
        const sB = (b.subcategory || "").toLowerCase();
        return isAsc ? sA.localeCompare(sB) : sB.localeCompare(sA);
      }
      if (key === "league") {
        const lA = (a.league || "").toLowerCase();
        const lB = (b.league || "").toLowerCase();
        return isAsc ? lA.localeCompare(lB) : lB.localeCompare(lA);
      }
      return 0;
    });
  }, [activeCategoriesList, categoriesSort, categoriesCategoryFilter]);

  const categoriesPageCount = Math.max(1, Math.ceil(sortedCategories.length / TABLE_PAGE_SIZE));
  const pagedCategories = useMemo(
    () =>
      sortedCategories.slice(
        (Math.min(categoriesPage, categoriesPageCount) - 1) * TABLE_PAGE_SIZE,
        Math.min(categoriesPage, categoriesPageCount) * TABLE_PAGE_SIZE
      ),
    [sortedCategories, categoriesPage, categoriesPageCount]
  );

  // Derived stats:
  // dbPnl is strictly from the database position ledger (used for progression windows & category breakdown)
  const dbPnl = num(stats?.total_pnl ?? stats?.pnl);
  // pmPnl is official Polymarket Leaderboard PnL (for the "Polymarket PnL" snapshot card)
  const pmPnl = num(stats?.pm_pnl ?? stats?.total_pnl ?? stats?.pnl);
  const pnl = dbPnl;
  const winRate = num(stats?.win_rate);
  const volume = num(stats?.total_volume ?? stats?.volume ?? stats?.pm_volume);
  const balance = num(stats?.balance);
  const roiPct = num(stats?.roi_pct ?? (volume && volume > 0 && dbPnl != null ? (dbPnl / volume * 100) : null));
  const positionValue = num(stats?.position_value);
  const avgBuyPrice = num(stats?.avg_buy_price);
  const winningCount = stats?.winning_count ?? stats?.wins_count;
  const losingCount = stats?.losing_count ?? stats?.losses_count ?? (stats?.resolved_count != null && stats?.winning_count != null ? Math.max(0, Number(stats.resolved_count) - Number(stats.winning_count)) : null);
  const tier = stats?.tier ? String(stats.tier).toUpperCase() : (statsLoading ? "..." : "STANDARD");

  // 10 PnL Windows (matches database columns pnl_100 .. pnl_5000)
  const pnlWindows: ProgressionWindowData[] = useMemo(() => {
    return [
      { label: "Last 100", value: num(stats?.pnl_100 ?? stats?.pnl_window_100) },
      { label: "Last 200", value: num(stats?.pnl_200 ?? stats?.pnl_window_200) },
      { label: "Last 300", value: num(stats?.pnl_300 ?? stats?.pnl_window_300) },
      { label: "Last 500", value: num(stats?.pnl_500 ?? stats?.pnl_window_500) },
      { label: "Last 750", value: num(stats?.pnl_750 ?? stats?.pnl_window_750) },
      { label: "Last 1000", value: num(stats?.pnl_1000 ?? stats?.pnl_window_1000) },
      { label: "Last 1500", value: num(stats?.pnl_1500 ?? stats?.pnl_window_1500) },
      { label: "Last 2000", value: num(stats?.pnl_2000 ?? stats?.pnl_window_2000) },
      { label: "Last 3500", value: num(stats?.pnl_3500 ?? stats?.pnl_window_3500) },
      { label: "All", value: num(stats?.pnl_all ?? stats?.pnl_5000 ?? stats?.total_pnl ?? stats?.pnl) },
    ];
  }, [stats]);

  // 6 Price Buckets (Where The Trader Bets)
  const priceBuckets: PriceBucketData[] = useMemo(() => {
    return [
      {
        label: "< 0.15",
        buys: stats?.buys_below_15c ?? stats?.bucket_0_15_buys ?? 0,
        wins: stats?.wins_below_15c ?? stats?.bucket_0_15_wins ?? 0,
        avgSell: num(stats?.avg_sell_below_15c ?? stats?.bucket_0_15_avg_sell),
      },
      {
        label: "0.15 - 0.30",
        buys: stats?.buys_15_30c ?? stats?.bucket_15_30_buys ?? 0,
        wins: stats?.wins_15_30c ?? stats?.bucket_15_30_wins ?? 0,
        avgSell: num(stats?.avg_sell_15_30c ?? stats?.bucket_15_30_avg_sell),
      },
      {
        label: "0.30 - 0.45",
        buys: stats?.buys_30_45c ?? stats?.bucket_30_45_buys ?? 0,
        wins: stats?.wins_30_45c ?? stats?.bucket_30_45_wins ?? 0,
        avgSell: num(stats?.avg_sell_30_45c ?? stats?.bucket_30_45_avg_sell),
      },
      {
        label: "0.45 - 0.60",
        buys: stats?.buys_45_60c ?? stats?.bucket_45_60_buys ?? 0,
        wins: stats?.wins_45_60c ?? stats?.bucket_45_60_wins ?? 0,
        avgSell: num(stats?.avg_sell_45_60c ?? stats?.bucket_45_60_avg_sell),
      },
      {
        label: "0.60 - 0.75",
        buys: stats?.buys_60_75c ?? stats?.bucket_60_75_buys ?? 0,
        wins: stats?.wins_60_75c ?? stats?.bucket_60_75_wins ?? 0,
        avgSell: num(stats?.avg_sell_60_75c ?? stats?.bucket_60_75_avg_sell),
      },
      {
        label: "> 0.75",
        buys: stats?.buys_above_75c ?? stats?.bucket_75_100_buys ?? 0,
        wins: stats?.wins_above_75c ?? stats?.bucket_75_100_wins ?? 0,
        avgSell: num(stats?.avg_sell_above_75c ?? stats?.bucket_75_100_avg_sell),
      },
    ];
  }, [stats]);

  return (
    <div className="w-full min-h-screen bg-background flex flex-col p-4 md:p-6 max-w-[1780px] mx-auto space-y-5">
      {/* ── Top Header Bar ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 flex-wrap pb-1">
        {/* Left: Back + Address + Badges */}
        <div className="flex items-center gap-3">
          <Link
            href="/wallets"
            className="p-2 rounded-xl bg-surface border border-border hover:bg-surface-2 text-foreground transition-all shadow-xs"
            title="Back to wallets list"
          >
            <ArrowLeft size={16} />
          </Link>

          <div className="flex items-center gap-2">
            <h1 className="text-xl sm:text-2xl font-bold font-mono text-foreground tracking-tight">
              {formatAddress(address)}
            </h1>
            <button
              onClick={copyAddress}
              className="p-1 rounded-md text-muted-fg hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
              title="Copy address"
            >
              {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
            </button>
          </div>

          {/* Badges */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full border border-border bg-surface-2 text-foreground uppercase tracking-wider font-mono">
              {tier}
            </span>

            {funding?.transferred_positions_count ? (
              <span className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full border border-border bg-surface text-foreground inline-flex items-center gap-1.5 font-mono shadow-xs">
                <GitFork size={12} className="text-muted-fg" />
                <span>Inherited Positions ({funding.transferred_positions_count})</span>
              </span>
            ) : funding?.funded_by ? (
              <Link
                href={`/wallet/${funding.funded_by}`}
                className="text-[11px] font-semibold px-2.5 py-0.5 rounded-full border border-border bg-surface text-foreground inline-flex items-center gap-1.5 hover:bg-surface-2 transition-colors font-mono shadow-xs"
              >
                <Link2 size={12} className="text-muted-fg" />
                <span>Funded by {funding.funder_username || formatAddress(funding.funded_by)}</span>
              </Link>
            ) : null}
          </div>
        </div>

        {/* Right: Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => loadData(true)}
            disabled={refreshing || statsLoading}
            className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-xl bg-surface border border-border hover:bg-surface-2 text-foreground transition-all shadow-xs cursor-pointer disabled:opacity-50"
          >
            <RotateCw size={13} className={refreshing ? "animate-spin text-primary" : "text-muted-fg"} />
            <span>Refresh</span>
          </button>

          <a
            href={`https://polymarket.com/profile/${address}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-xl bg-surface border border-border hover:bg-surface-2 text-foreground transition-all shadow-xs cursor-pointer"
          >
            <Globe size={13} className="text-muted-fg" />
            <span>Polymarket</span>
          </a>

          <a
            href={`https://polygonscan.com/address/${address}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-xl bg-surface border border-border hover:bg-surface-2 text-foreground transition-all shadow-xs cursor-pointer"
          >
            <ExternalLink size={13} className="text-muted-fg" />
            <span>Polygonscan</span>
          </a>

          <a
            href={`https://activity.polymarket-tools.com/?address=${address}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-xl bg-surface border border-border hover:bg-surface-2 text-foreground transition-all shadow-xs cursor-pointer"
          >
            <Box size={13} className="text-muted-fg" />
            <span>PolyTools</span>
          </a>

          <div className="pl-1">
            <LikeButton
              isLiked={isLiked(address)}
              onToggle={handleToggleFavorite}
              favoriteCount={favoriteCount}
              size={15}
            />
          </div>
        </div>
      </div>

      {/* ── Main Dashboard Layout (Left 74% + Right 26% Live Trade Stream) ── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        {/* ── LEFT & CENTER MAIN COLUMN (9 of 12 cols = 75%) ─────────────── */}
        <div className="xl:col-span-9 space-y-5">
          {/* Row 2: Where Trader Bets (Matrix) + 10-Window Progression (Spline) */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <TraderBetsMatrix buckets={priceBuckets} />
            <HistoricalProgressionChart windows={pnlWindows} overallPnl={pnl} />
          </div>

          {/* Row 3: ONE UNIFIED PANEL FOR ALL 5 DATA TABLES ──────────────── */}
          <div className="flex flex-col rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
            {/* Unified Tab Bar Header */}
            <div className="px-4 py-2 bg-surface-2/40 border-b border-border flex items-center justify-between flex-wrap gap-2 flex-shrink-0">
              <div className="flex items-center gap-2 sm:gap-4 overflow-x-auto py-1">
                {/* 1. Category Win Rates */}
                <button
                  onClick={() => switchActiveTab("categories")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "categories"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <Layers size={13} className="text-muted-fg" />
                  <span>Category Win Rates</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {sortedCategories.length > 0 ? sortedCategories.length : (categoriesLoading ? "..." : "0")}
                  </span>
                </button>

                {/* 2. Closed Positions */}
                <button
                  onClick={() => switchActiveTab("closed")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "closed"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <History size={13} className="text-muted-fg" />
                  <span>Closed Positions</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {closedPositions.length > 0 ? closedPositions.length : stats?.resolved_count ?? (closedPositionsLoading ? "..." : "0")}
                  </span>
                </button>

                {/* 3. Open Positions */}
                <button
                  onClick={() => switchActiveTab("open")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "open"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <Briefcase size={13} className="text-muted-fg" />
                  <span>Open Positions</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {positions.length > 0 ? positions.length : stats?.open_positions_count ?? stats?.open_count ?? (openPositionsLoading ? "..." : "0")}
                  </span>
                </button>

                {/* 4. Closed Parlays */}
                <button
                  onClick={() => switchActiveTab("closed_parlay")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "closed_parlay"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <History size={13} className="text-muted-fg" />
                  <span>Closed Parlays</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {closedParlays.length > 0 ? closedParlays.length : stats?.parlay_count ?? (parlaysLoading ? "..." : "0")}
                  </span>
                </button>

                {/* 5. Open Parlays */}
                <button
                  onClick={() => switchActiveTab("open_parlay")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "open_parlay"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <Zap size={13} className="text-muted-fg" />
                  <span>Open Parlays</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {openParlays.length > 0 ? openParlays.length : (parlaysLoading ? "..." : "0")}
                  </span>
                </button>

                {/* 6. Source Integrity */}
                <button
                  onClick={() => switchActiveTab("integrity")}
                  className={`text-xs font-bold uppercase tracking-wider transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                    activeTab === "integrity"
                      ? "text-foreground font-extrabold pb-0.5 border-b-2 border-primary"
                      : "text-muted-fg hover:text-foreground"
                  }`}
                >
                  <Check size={13} className="text-muted-fg" />
                  <span>Data Integrity</span>
                  <span className="px-2 py-0.2 rounded-full bg-surface-2 text-foreground border border-border text-[9px] font-bold font-mono">
                    {reconciliation?.positions?.length ?? (reconciliationLoading ? "..." : "0")}
                  </span>
                </button>
              </div>

              {/* Category & Status Filter Controls */}
              {((activeTab === "open" && !openPositionsLoading) || (activeTab === "closed" && !closedPositionsLoading) || (activeTab === "open_parlay" && !parlaysLoading) || (activeTab === "closed_parlay" && !parlaysLoading)) && (
                <div className="flex items-center gap-2 flex-wrap">
                  {activeTab === "closed" && (
                    <>
                      <ClosedOutcomeFilterSelect
                        value={closedPositionsOutcomeFilter}
                        onChange={(v) => {
                          setClosedPositionsOutcomeFilter(v);
                          setClosedPositionsPage(1);
                        }}
                      />
                      <ClosedSubFilterSelect
                        value={closedPositionsSubFilter}
                        onChange={(v) => {
                          setClosedPositionsSubFilter(v);
                          setClosedPositionsPage(1);
                        }}
                      />
                    </>
                  )}
                  <CategoryFilterSelect
                    value={
                      activeTab === "open"
                        ? openPositionsCategoryFilter
                        : activeTab === "closed"
                        ? closedPositionsCategoryFilter
                        : activeTab === "open_parlay"
                        ? openParlaysCategoryFilter
                        : closedParlaysCategoryFilter
                    }
                    onChange={(v) => {
                      if (activeTab === "open") {
                        setOpenPositionsCategoryFilter(v);
                        setOpenPositionsPage(1);
                      } else if (activeTab === "closed") {
                        setClosedPositionsCategoryFilter(v);
                        setClosedPositionsPage(1);
                      } else if (activeTab === "open_parlay") {
                        setOpenParlaysCategoryFilter(v);
                        setOpenParlaysPage(1);
                      } else if (activeTab === "closed_parlay") {
                        setClosedParlaysCategoryFilter(v);
                        setClosedParlaysPage(1);
                      }
                    }}
                    options={uniqCategories(
                      activeTab === "open"
                        ? positions
                        : activeTab === "closed"
                        ? closedPositions
                        : activeTab === "open_parlay"
                        ? openParlays
                        : closedParlays
                    )}
                  />
                </div>
              )}

              {/* Category Scope & Category Filter Dropdowns (for Category Win Rates tab) */}
              {activeTab === "categories" && (
                <div className="flex items-center gap-2 flex-wrap">
                  <CategoryFilterSelect
                    value={categoriesCategoryFilter}
                    onChange={(v) => {
                      setCategoriesCategoryFilter(v);
                      setCategoriesPage(1);
                    }}
                    options={uniqCategories(activeCategoriesList)}
                  />
                  <CategoryScopeSelect
                    value={categoryScope}
                    onChange={(v) => {
                      setCategoryScope(v);
                      setCategoriesPage(1);
                    }}
                  />
                </div>
              )}
            </div>

            {activeTab === "integrity" && (
              <div className="p-4 space-y-4 overflow-x-auto">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold">Activity vs. Position Evidence</h3>
                    <p className="text-[11px] text-muted-fg mt-1">Review classifications only; canonical PnL is not changed by this panel.</p>
                  </div>
                  <span className="text-[10px] font-mono text-muted-fg">
                    {reconciliation?.scan_state?.baseline_complete ? "Complete baseline" : "No complete baseline"}
                  </span>
                </div>
                {reconciliationLoading ? (
                  <div className="text-xs text-muted-fg py-8 text-center">Loading reconciliation evidence…</div>
                ) : !reconciliation ? (
                  <div className="text-xs text-muted-fg py-8 text-center">No Activity reconciliation has been run for this wallet.</div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(reconciliation.classification_counts || {}).map(([key, value]) => (
                        <span key={key} className="px-2 py-1 rounded border border-border bg-surface-2 text-[10px] font-mono">
                          {key}: {String(value)}
                        </span>
                      ))}
                    </div>
                    <table className="w-full text-xs text-left min-w-[900px]">
                      <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono text-[10px] border-b border-border">
                        <tr>
                          <th className="py-2 px-2">Market ID</th><th className="py-2 px-2">DB outcome</th>
                          <th className="py-2 px-2">Classification</th><th className="py-2 px-2 text-right">DB shares</th>
                          <th className="py-2 px-2 text-right">Activity BUY</th><th className="py-2 px-2 text-right">SELL</th>
                          <th className="py-2 px-2 text-right">REDEEM</th><th className="py-2 px-2">Activity outcomes</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/50">
                        {(reconciliation.positions || []).filter((row: any) => row.classification !== "direct_activity_buy" || row.comparison_quality !== "exact_activity_buy").map((row: any) => (
                          <tr key={`${row.condition_id}-${row.outcome}`}>
                            <td className="py-2 px-2 font-mono text-[10px]">{String(row.condition_id).slice(0, 14)}…</td>
                            <td className="py-2 px-2">{row.outcome || "—"}</td>
                            <td className="py-2 px-2">{row.classification}</td>
                            <td className="py-2 px-2 text-right font-mono">{num(row.db_total_bought)?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—"}</td>
                            <td className="py-2 px-2 text-right font-mono">{num(row.activity_buy_shares)?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—"}</td>
                            <td className="py-2 px-2 text-right font-mono">{num(row.activity_sell_shares)?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—"}</td>
                            <td className="py-2 px-2 text-right font-mono">{num(row.activity_redeem_shares)?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—"}</td>
                            <td className="py-2 px-2">{Array.isArray(row.activity_outcomes) ? row.activity_outcomes.join(", ") : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!!reconciliation.activity_only_markets?.length && (
                      <div>
                        <h4 className="text-xs font-bold mb-2">Activity-only markets</h4>
                        <div className="text-[11px] text-muted-fg">{reconciliation.activity_only_markets.length} markets tracked for open/redeemable/lifecycle status.</div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Tab 1: Live Open Positions Table */}
            {activeTab === "open" && (
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-xs text-left table-fixed min-w-[700px]">
                  <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono tracking-wider text-[10px] border-b border-border">
                    <tr>
                      <SortHeader label="Market" sortKey="market" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="left" className="w-[36%]" />
                      <SortHeader label="Outcome" sortKey="outcome" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="center" className="w-[9%] px-2" />
                      <SortHeader label="Tokens" sortKey="tokens" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Avg Entry" sortKey="avgEntry" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Invested" sortKey="invested" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Current Value" sortKey="currentValue" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="PnL" sortKey="pnl" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Opened" sortKey="date" currentKey={openPositionsSort.key} currentDir={openPositionsSort.dir} onSort={(k) => { handleSort(setOpenPositionsSort)(k); setOpenPositionsPage(1); }} align="right" className="w-[8%]" />
                    </tr>
                  </thead>
                  {openPositionsLoading ? (
                    <SkeletonTableRows rows={6} cols={8} />
                  ) : (
                    <tbody className="divide-y divide-border/50">
                      {pagedOpenPositions.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-14 text-center text-muted-fg text-xs">
                            <div className="flex flex-col items-center justify-center space-y-2">
                              <Briefcase size={22} className="text-muted-fg/40" />
                              <span className="font-medium">No active open positions.</span>
                              <span className="text-[10px] text-muted-fg">When the wallet opens new positions, they will appear here.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        pagedOpenPositions.map((p, i) => {
                          const rawSide = String(p.side || p.outcome || "").trim();
                          const isTokenId = rawSide.length > 20 && /^\d+$/.test(rawSide);
                          const side = isTokenId ? "YES" : (rawSide.toUpperCase() || "—");
                          const tokens = num(p.totalBought ?? p.size) || 0;
                          const avgP = num(p.avgPrice) || 0;
                          const curVal = num(p.currentValue);
                          const pnlVal = num(p.cashPnl ?? p.unrealizedPnl ?? p.pnl);
                          const investedVal = tokens > 0 && avgP > 0 ? tokens * avgP : curVal != null && pnlVal != null ? Math.max(0, curVal - pnlVal) : null;
                          const openedDate = (() => {
                            const raw = p.entryAt ?? p.entry_at ?? p.timestamp ?? p.dateOpened;
                            if (!raw) return null;
                            const d = new Date(typeof raw === "number" ? (raw > 1e12 ? raw : raw * 1000) : raw);
                            return isNaN(d.getTime()) ? null : d;
                          })();
                          return (
                            <tr key={`${p.conditionId || 'open'}-${p.outcome || ''}-${p.asset || ''}-${i}`} className="hover:bg-surface-2/40 transition-colors">
                              <td className="py-2.5 px-3">
                                <MarketTitleCell
                                  title={p.title || p.market_title || p.market}
                                  conditionId={p.conditionId}
                                  slug={p.slug}
                                  eventSlug={p.eventSlug}
                                  asset={p.asset}
                                />
                              </td>
                              <td className="py-2.5 px-2 text-center">
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                                    side === "YES"
                                      ? "bg-green-500/10 text-green-600 border-green-500/20"
                                      : side === "NO"
                                      ? "bg-red-500/10 text-red-600 border-red-500/20"
                                      : "bg-primary/10 text-primary border-primary/20"
                                  }`}
                                >
                                  {side || "—"}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono">
                                {tokens > 0 ? tokens.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                {avgP > 0 ? `${(avgP * 100).toFixed(1)}¢` : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-semibold text-foreground">
                                {investedVal != null ? formatCurrency(investedVal) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-medium text-muted-fg">
                                {curVal != null ? formatCurrency(curVal) : "—"}
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono font-bold ${pnlVal != null && pnlVal >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {pnlVal != null ? signedCurrency(pnlVal, true) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg whitespace-nowrap">
                                {openedDate ? openedDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" }) : "—"}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  )}
                </table>
                <PaginationFooter
                  page={Math.min(openPositionsPage, openPositionsPageCount)}
                  pageCount={openPositionsPageCount}
                  total={sortedPositions.length}
                  onPage={setOpenPositionsPage}
                />
              </div>
            )}

            {/* Tab 2: Closed Resolved Positions Table */}
            {activeTab === "closed" && (
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-xs text-left table-fixed min-w-[650px]">
                  <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono tracking-wider text-[10px] border-b border-border">
                    <tr>
                      <SortHeader label="Market" sortKey="market" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="left" className="w-[42%]" />
                      <SortHeader label="Outcome" sortKey="outcome" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="center" className="w-[9%] px-2" />
                      <SortHeader label="Tokens" sortKey="tokens" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Avg Entry" sortKey="avgEntry" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Invested" sortKey="invested" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Date" sortKey="date" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Realized PnL" sortKey="pnl" currentKey={closedPositionsSort.key} currentDir={closedPositionsSort.dir} onSort={(k) => { handleSort(setClosedPositionsSort)(k); setClosedPositionsPage(1); }} align="right" className="w-[11%]" />
                    </tr>
                  </thead>
                  {closedPositionsLoading ? (
                    <SkeletonTableRows rows={6} cols={7} />
                  ) : (
                    <tbody className="divide-y divide-border/50">
                      {pagedClosedPositions.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="py-14 text-center text-muted-fg text-xs">
                            <div className="flex flex-col items-center justify-center space-y-2">
                              <History size={22} className="text-muted-fg/40" />
                              <span className="font-medium">No closed positions recorded.</span>
                              <span className="text-[10px] text-muted-fg">Resolved positions will appear here.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        pagedClosedPositions.map((cp, i) => {
                          const realized = num(cp.realizedPnl ?? cp.cashPnl ?? cp.pnl);
                          const rawOutcome = String(cp.outcome || "").trim();
                          const isTokenId = rawOutcome.length > 20 && /^\d+$/.test(rawOutcome);
                          const outcome = isTokenId ? "YES" : (rawOutcome.toUpperCase() || "—");
                          const tokens = num(cp.totalBought ?? cp.size) || 0;
                          const avgP = num(cp.avgPrice) || 0;
                          const investedVal = tokens > 0 && avgP > 0 ? tokens * avgP : null;
                          const effDate = getEffectiveClosedDate(cp);
                          return (
                            <tr key={`${cp.conditionId || 'closed'}-${cp.outcome || ''}-${cp.asset || ''}-${i}`} className="hover:bg-surface-2/40 transition-colors">
                              <td className="py-2.5 px-3">
                                <MarketTitleCell
                                  title={cp.title || cp.market_title || cp.market}
                                  conditionId={cp.conditionId}
                                  slug={cp.slug}
                                  eventSlug={cp.eventSlug}
                                  asset={cp.asset}
                                />
                              </td>
                              <td className="py-2.5 px-2 text-center">
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                                    outcome === "YES"
                                      ? "bg-green-500/10 text-green-600 border-green-500/20"
                                      : outcome === "NO"
                                      ? "bg-red-500/10 text-red-600 border-red-500/20"
                                      : "bg-primary/10 text-primary border-primary/20"
                                  }`}
                                >
                                  {outcome || "—"}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono">
                                {tokens > 0 ? tokens.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                {avgP > 0 ? `${(avgP * 100).toFixed(1)}¢` : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-semibold text-foreground">
                                {investedVal != null ? formatCurrency(investedVal) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg text-[11px] whitespace-nowrap">
                                {effDate?.dateStr || "—"}
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono font-bold ${realized != null && realized >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {realized != null ? signedCurrency(realized, true) : "—"}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  )}
                </table>
                <PaginationFooter
                  page={Math.min(closedPositionsPage, closedPositionsPageCount)}
                  pageCount={closedPositionsPageCount}
                  total={sortedClosedPositions.length}
                  onPage={setClosedPositionsPage}
                />
              </div>
            )}

            {/* Tab 3: Open Parlays Table */}
            {activeTab === "open_parlay" && (
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-xs text-left table-fixed min-w-[650px]">
                  <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono tracking-wider text-[10px] border-b border-border">
                    <tr>
                      <SortHeader label="Parlay Market" sortKey="market" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="left" className="w-[40%]" />
                      <SortHeader label="Tokens" sortKey="tokens" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Avg Entry" sortKey="avgEntry" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Invested" sortKey="invested" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Current Value" sortKey="currentValue" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Unrealized PnL" sortKey="pnl" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Opened" sortKey="date" currentKey={openParlaysSort.key} currentDir={openParlaysSort.dir} onSort={(k) => { handleSort(setOpenParlaysSort)(k); setOpenParlaysPage(1); }} align="right" className="w-[10%]" />
                    </tr>
                  </thead>
                  {parlaysLoading ? (
                    <SkeletonTableRows rows={6} cols={7} />
                  ) : (
                    <tbody className="divide-y divide-border/50">
                      {pagedOpenParlays.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="py-14 text-center text-muted-fg text-xs">
                            <div className="flex flex-col items-center justify-center space-y-2">
                              <Zap size={22} className="text-muted-fg/40" />
                              <span className="font-medium">No active open parlay positions.</span>
                              <span className="text-[10px] text-muted-fg">Your active parlay positions will appear here.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        pagedOpenParlays.map((op, idx) => {
                          const curVal = num(op.currentValue);
                          const pnlVal = num(op.cashPnl ?? op.unrealizedPnl);
                          const tokens = num(op.tokens ?? op.size) || 0;
                          const avgP = num(op.avgPrice) || 0;
                          const investedVal = num(op.invested) || (tokens > 0 && avgP > 0 ? tokens * avgP : curVal);
                          const rowKey = op.conditionId ? `${op.conditionId}-${op.asset || idx}` : `open-parlay-${idx}`;
                          const openedDate = (() => {
                            const raw = op.entryAt ?? op.entry_at ?? op.timestamp ?? op.dateOpened;
                            if (!raw) return null;
                            const d = new Date(typeof raw === "number" ? (raw > 1e12 ? raw : raw * 1000) : raw);
                            return isNaN(d.getTime()) ? null : d;
                          })();
                          return (
                            <tr key={rowKey} className="hover:bg-surface-2/40 transition-colors">
                              <td className="py-2.5 px-3">
                                <MarketTitleCell
                                  title={op.title || op.market_title || op.market}
                                  conditionId={op.conditionId}
                                  slug={op.slug}
                                  eventSlug={op.eventSlug}
                                  asset={op.asset}
                                />
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono">
                                {tokens > 0 ? tokens.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                {avgP > 0 ? `${(avgP * 100).toFixed(1)}¢` : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-semibold text-foreground">
                                {investedVal != null ? formatCurrency(investedVal) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-medium text-muted-fg">
                                {curVal != null ? formatCurrency(curVal) : "—"}
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono font-bold ${pnlVal != null && pnlVal >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {pnlVal != null ? signedCurrency(pnlVal, true) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg whitespace-nowrap">
                                {openedDate ? openedDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" }) : "—"}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  )}
                </table>
                <PaginationFooter
                  page={Math.min(openParlaysPage, openParlaysPageCount)}
                  pageCount={openParlaysPageCount}
                  total={sortedOpenParlays.length}
                  onPage={setOpenParlaysPage}
                />
              </div>
            )}

            {/* Tab 4: Closed Parlays Table */}
            {activeTab === "closed_parlay" && (
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-xs text-left table-fixed min-w-[650px]">
                  <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono tracking-wider text-[10px] border-b border-border">
                    <tr>
                      <SortHeader label="Parlay Market" sortKey="market" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="left" className="w-[42%]" />
                      <SortHeader label="Result" sortKey="result" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="center" className="w-[9%] px-2" />
                      <SortHeader label="Tokens" sortKey="tokens" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Avg Entry" sortKey="avgEntry" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="right" className="w-[9%]" />
                      <SortHeader label="Invested" sortKey="invested" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Date" sortKey="date" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="right" className="w-[10%]" />
                      <SortHeader label="Realized PnL" sortKey="pnl" currentKey={closedParlaysSort.key} currentDir={closedParlaysSort.dir} onSort={(k) => { handleSort(setClosedParlaysSort)(k); setClosedParlaysPage(1); }} align="right" className="w-[11%]" />
                    </tr>
                  </thead>
                  {parlaysLoading ? (
                    <SkeletonTableRows rows={6} cols={7} />
                  ) : (
                    <tbody className="divide-y divide-border/50">
                      {pagedClosedParlays.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="py-14 text-center text-muted-fg text-xs">
                            <div className="flex flex-col items-center justify-center space-y-2">
                              <History size={22} className="text-muted-fg/40" />
                              <span className="font-medium">No closed parlay records found.</span>
                              <span className="text-[10px] text-muted-fg">Resolved parlay positions will appear here.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        pagedClosedParlays.map((cp, idx) => {
                          const realized = num(cp.realizedPnl ?? cp.cashPnl ?? cp.pnl);
                          const isWin = realized != null && realized > 0;
                          const tokens = num(cp.tokens ?? cp.size ?? cp.totalBought) || 0;
                          const rawAvgP = num(cp.avgPrice ?? cp.avg_buy_price ?? cp.avgBuyPrice);

                          let avgP = rawAvgP && rawAvgP > 0 ? rawAvgP : null;
                          let entryCost = num(cp.entryCost);

                          if (entryCost == null && tokens > 0 && avgP != null && avgP > 0) {
                            entryCost = tokens * avgP;
                          }

                          // Fallback inference if avgPrice was omitted by the API
                          if (entryCost == null && tokens > 0 && realized != null && realized > 0) {
                            if (tokens > realized) {
                              entryCost = tokens - realized;
                              if (avgP == null) avgP = (tokens - realized) / tokens;
                            } else if (tokens === realized) {
                              entryCost = 0;
                              if (avgP == null) avgP = 1.0;
                            }
                          }

                          const effDate = getEffectiveClosedDate(cp);
                          const rowKey = cp.conditionId ? `${cp.conditionId}-${cp.outcome || idx}` : `closed-parlay-${idx}`;
                          return (
                            <tr key={rowKey} className="hover:bg-surface-2/40 transition-colors">
                              <td className="py-2.5 px-3">
                                <MarketTitleCell
                                  title={cp.title || cp.market_title || cp.market}
                                  conditionId={cp.conditionId}
                                  slug={cp.slug}
                                  eventSlug={cp.eventSlug}
                                  asset={cp.asset}
                                />
                              </td>
                              <td className="py-2.5 px-2 text-center">
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                                    isWin
                                      ? "bg-green-500/10 text-green-600 border-green-500/20"
                                      : "bg-red-500/10 text-red-600 border-red-500/20"
                                  }`}
                                >
                                  {isWin ? "WON" : "RESOLVED"}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono">
                                {tokens > 0 ? tokens.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                {avgP != null && avgP > 0 ? `${(avgP * 100).toFixed(1)}¢` : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-semibold text-foreground">
                                {entryCost != null ? (entryCost === 0 ? "$0" : formatCurrency(entryCost)) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg text-[11px] whitespace-nowrap">
                                {effDate?.dateStr || "—"}
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono font-bold ${realized != null && realized >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {realized != null ? signedCurrency(realized, true) : "—"}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  )}
                </table>
                <PaginationFooter
                  page={Math.min(closedParlaysPage, closedParlaysPageCount)}
                  pageCount={closedParlaysPageCount}
                  total={sortedClosedParlays.length}
                  onPage={setClosedParlaysPage}
                />
              </div>
            )}

            {/* Tab 5: Category, Subcategory & League Win Rates Table with Pagination */}
            {activeTab === "categories" && (
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-xs text-left min-w-[700px]">
                  <thead className="bg-surface-2/60 text-muted-fg uppercase font-mono tracking-wider text-[10px] border-b border-border">
                    <tr>
                      <SortHeader label="Category" sortKey="category" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="left" />
                      <SortHeader label="Subcategory" sortKey="subcategory" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="left" />
                      <SortHeader label="League" sortKey="league" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="left" />
                      <SortHeader label="Win Rate" sortKey="winRate" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="right" />
                      <SortHeader label="W / L" sortKey="resolved" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="right" />
                      <SortHeader label="PnL" sortKey="pnl" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="right" />
                      <SortHeader label="Volume" sortKey="volume" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="right" />
                      <SortHeader label="ROI%" sortKey="roi" currentKey={categoriesSort.key} currentDir={categoriesSort.dir} onSort={handleSort(setCategoriesSort)} align="right" />
                    </tr>
                  </thead>
                  {categoriesLoading ? (
                    <SkeletonTableRows rows={6} cols={8} />
                  ) : (
                    <tbody className="divide-y divide-border/50">
                      {pagedCategories.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-14 text-center text-muted-fg text-xs">
                            <div className="flex flex-col items-center justify-center space-y-2">
                              <Layers size={22} className="text-muted-fg/40" />
                              <span className="font-medium">No category stats recorded.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        pagedCategories.map((c, i) => {
                          const isOverall = (c.category || "OVERALL").toUpperCase() === "OVERALL";
                          const catWr = num(c.win_rate);
                          const catPnl = num(c.pnl);
                          const catVol = num(c.volume);
                          const catRoi = num(c.roi_pct);
                          const wins = c.winning_count || 0;
                          const losses = c.losing_count || 0;

                          return (
                            <tr
                              key={`${c.category}-${c.subcategory}-${i}`}
                              className={`hover:bg-surface-2/40 transition-colors ${
                                isOverall ? "bg-primary/[0.03] font-semibold" : ""
                              }`}
                            >
                              <td className="py-2.5 px-3 text-foreground font-bold uppercase tracking-wide">
                                {c.category || "OVERALL"}
                              </td>
                              <td className="py-2.5 px-3 font-medium text-foreground">
                                {c.subcategory ? (
                                  <span className="text-foreground font-mono text-[11px]">
                                    {c.subcategory}
                                  </span>
                                ) : (
                                  <span className="text-muted-fg text-[11px]">—</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3">
                                {c.league ? (
                                  <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium whitespace-nowrap">
                                    {c.league}
                                  </span>
                                ) : (
                                  <span className="text-muted-fg text-[11px]">—</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono font-bold text-foreground">
                                {formatPercent(catWr)}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                <span className="text-green-600 font-semibold">{wins}</span> /{" "}
                                <span className="text-red-500 font-semibold">{losses}</span>
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono font-bold ${catPnl != null && catPnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {catPnl != null ? signedCurrency(catPnl, true) : "—"}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono text-muted-fg">
                                {catVol != null ? formatCurrency(catVol) : "—"}
                              </td>
                              <td className={`py-2.5 px-3 text-right font-mono ${catRoi != null && catRoi >= 0 ? "text-green-600" : "text-red-500"}`}>
                                {catRoi != null ? `${catRoi > 0 ? "+" : ""}${catRoi.toFixed(1)}%` : "—"}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  )}
                </table>
                <PaginationFooter
                  page={Math.min(categoriesPage, categoriesPageCount)}
                  pageCount={categoriesPageCount}
                  total={sortedCategories.length}
                  onPage={setCategoriesPage}
                />
              </div>
            )}
          </div>

          {/* Row 4: Lineage & Capital Flow Graph ──────────────────────── */}
          <LineageFlowGraph
            address={address}
            username={stats?.username}
            tier={stats?.tier}
            balance={balance || 0}
            positionValue={positionValue || 0}
            funding={funding}
            positionTransfers={positionTransfers}
            depositsTotal={num(stats?.deposits) || 0}
          />
        </div>

        {/* ── RIGHT COLUMN: SNAPSHOT → TOP CATEGORIES → LIVE STREAM ── */}
        <div className="xl:col-span-3">
          <div className="sticky top-4 space-y-5">
            {!statsLoading && (
              <WalletSideRail
                tier={tier}
                pnl={pmPnl}
                winRate={winRate}
                winningCount={winningCount}
                losingCount={losingCount}
                volume={volume}
                roiPct={roiPct}
                balance={balance}
                depositsTotal={num(stats?.deposits)}
                favoriteCount={favoriteCount}
                positionsCount={positions.length}
                positionValue={positionValue}
                categories={activeCategoriesList}
                loading={statsLoading || categoriesLoading}
              />
            )}
            <LiveTradeStreamPanel
              trades={trades}
              walletAddress={address}
              onRefresh={() => loadTrades(address)}
              loading={tradesLoading}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
