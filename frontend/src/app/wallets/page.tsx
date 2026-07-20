"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search } from "lucide-react";
import { getWalletCounts } from "@/utils/api";
import { formatCurrency, timeAgo } from "@/utils/format";
import { useWalletList } from "@/hooks/useWalletList";
import { useCopyAddress } from "@/hooks/useCopyAddress";
import { useWatchlistAdd } from "@/hooks/useWatchlistAdd";
import { WalletTable, WalletRow, ColumnDef } from "@/components/wallets/WalletTable";
import { WalletCell } from "@/components/wallets/WalletCell";
import { SourceBadges, MightCookBadge } from "@/components/wallets/SourceBadges";
import { Pagination } from "@/components/wallets/Pagination";
import { StatCard, StatCardRow } from "@/components/ui/StatCard";
import { PillTabs } from "@/components/ui/PillTabs";
import { Globe as GlobeIcon, Activity, Moon, Sparkles } from "lucide-react";

const TABS = [
  { key: "all", label: "All", description: "Every tracked wallet that isn't dead" },
  { key: "standard", label: "Standard", description: "Balance + positions ≥ $1k with trading history — active whales" },
  { key: "low_balance", label: "Low Balance", description: "Balance + positions under $1k" },
  { key: "new", label: "New", description: "Funded with $1k+ but hasn't made a trade yet" },
  { key: "hibernated", label: "Hibernated", description: "No trades in 30+ days" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const SOURCE_FILTER_OPTIONS = [
  { value: "", label: "All Sources" },
  { value: "trade", label: "Trade" },
  { value: "deposit", label: "Deposit" },
  { value: "leaderboard", label: "Leaderboard" },
  { value: "custom", label: "Custom" },
];

const DEFAULT_SORT: Record<TabKey, { field: string; order: "asc" | "desc" }> = {
  all: { field: "pnl", order: "desc" },
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

  const { copiedAddress, handleCopy } = useCopyAddress();
  const { watchlistStatus, handleAddToWatchlist } = useWatchlistAdd();

  useEffect(() => {
    getWalletCounts().then(setCounts).catch(() => setCounts(null));
  }, []);

  // Reset paging/sort when the tab changes
  useEffect(() => {
    setSortField(DEFAULT_SORT[tab].field);
    setSortOrder(DEFAULT_SORT[tab].order);
    setPage(1);
  }, [tab]);

  const { wallets, total, loading } = useWalletList({
    tab,
    source: sourceFilter || undefined,
    search: searchQuery || undefined,
    sort_by: sortField,
    sort_order: sortOrder,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

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
    const source: ColumnDef = {
      key: "source",
      label: "Source",
      render: (w) => <SourceBadges sources={w.sources} />,
    };
    const pnl: ColumnDef = { key: "pnl", label: "PnL", sortable: true, render: (w) => signedCurrency(w.pnl, true) };
    const volume: ColumnDef = {
      key: "volume",
      label: "Volume",
      sortable: true,
      render: (w) => {
        const n = num(w.volume);
        return n == null ? <>—</> : <>{formatCurrency(n)}</>;
      },
    };
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
    const balance: ColumnDef = { key: "balance", label: "Balance", sortable: true, render: (w) => plainCurrency(w.balance) };
    const position: ColumnDef = {
      key: "position_value",
      label: "Open Position",
      sortable: true,
      render: (w) => plainCurrency(w.position_value),
    };
    const lastTraded: ColumnDef = {
      key: "last_trade_at",
      label: "Last Traded",
      sortable: true,
      render: (w) => relativeDate(w.last_trade_at),
    };

    const withdrawals: ColumnDef = { key: "withdrawals", label: "Withdrawals", sortable: true, render: (w) => plainCurrency(w.withdrawals) };

    if (tab === "new") {
      return [
        wallet,
        source,
        balance,
        { key: "deposits", label: "Deposits", sortable: true, render: (w) => plainCurrency(w.deposits) },
        withdrawals,
        position,
        { key: "last_trade_at", label: "First Trade", sortable: true, render: (w) => relativeDate(w.added_at) },
      ];
    }
    if (tab === "low_balance") {
      return [wallet, source, pnl, volume, roi, balance, position, lastTraded];
    }
    if (tab === "hibernated") {
      return [
        wallet,
        source,
        pnl,
        volume,
        roi,
        balance,
        position,
        {
          key: "last_trade_at",
          label: "Dormant Since",
          sortable: true,
          render: (w) => {
            const t = timeAgo(w.last_trade_at);
            if (!t) return <>—</>;
            return (
              <span className="text-muted-fg">
                {new Date(w.last_trade_at!).toLocaleDateString()} <span className="opacity-70">({t.relative})</span>
              </span>
            );
          },
        },
      ];
    }
    return [wallet, source, pnl, volume, roi, balance, position, lastTraded];
  }, [tab, copiedAddress, handleCopy, watchlistStatus, handleAddToWatchlist]);

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
      {/* Stat cards */}
      <StatCardRow>
        <StatCard
          label="Total wallets"
          icon={<GlobeIcon size={16} />}
          value={counts ? counts.all.toLocaleString() : "—"}
          subtitle="Discovered across all sources"
        />
        <StatCard
          label="Active"
          icon={<Activity size={16} />}
          value={activeCount != null ? activeCount.toLocaleString() : "—"}
          valueClassName="text-primary"
          subtitle="Traded in the last 30 days"
        />
        <StatCard
          label="New"
          icon={<Sparkles size={16} />}
          value={counts ? counts.new.toLocaleString() : "—"}
          subtitle="Funded $1k+, no trades yet"
        />
        <StatCard
          label="Hibernated"
          icon={<Moon size={16} />}
          value={inactiveCount != null ? inactiveCount.toLocaleString() : "—"}
          subtitle="No trades in 30+ days"
        />
      </StatCardRow>

      {/* Tab bar */}
      <div className="mb-3">
        <PillTabs
          tabs={TABS.map((t) => ({ key: t.key, label: t.label, count: tabCount(t.key) }))}
          active={tab}
          onChange={(k) => switchTab(k as TabKey)}
        />
      </div>
      <p className="text-xs text-subtle flex-shrink-0 mb-3">{activeTab.description}</p>

      {/* Source filter pills + search */}
      <div className="flex items-center gap-2 flex-shrink-0 mb-3 flex-wrap">
        {SOURCE_FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => {
              setSourceFilter(opt.value);
              setPage(1);
            }}
            className={`px-3 py-1 text-[11px] font-semibold rounded-full uppercase tracking-wider transition-colors border ${
              sourceFilter === opt.value
                ? "bg-primary/15 text-primary border-primary/30"
                : "text-subtle bg-surface border-border hover:text-foreground"
            }`}
          >
            {opt.label}
          </button>
        ))}

        <div className="relative ml-auto">
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

      {/* Table */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden flex-1 min-h-0 flex flex-col shadow-sm">
        <WalletTable
          columns={columns}
          rows={wallets}
          loading={loading}
          sortField={sortField}
          sortOrder={sortOrder}
          onSort={handleSort}
          emptyMessage="No wallets found"
          rowOffset={(page - 1) * PAGE_SIZE}
        />
        <Pagination page={page} totalPages={totalPages} totalCount={total} onPageChange={setPage} />
      </div>
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
