"use client";

import { useEffect, useState } from "react";
import { getSmartMoneyAlerts, getAlphaCallsSummary, toggleWatchlist } from "@/utils/api";
import { formatCurrency, formatAddress, timeAgo } from "@/utils/format";
import Link from "next/link";
import { Radio, ArrowLeftRight, ArrowDownToLine, Flame, Copy, Check, PlusCircle } from "lucide-react";
import { StatCard, StatCardRow } from "@/components/ui/StatCard";
import { PillTabs } from "@/components/ui/PillTabs";
import { TypeBadge } from "@/components/ui/TypeBadge";
import { TierBadge } from "@/components/ui/TierBadge";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";

type TabKey = "all" | "trades" | "deposits";

// Wallet-quality tier from the CURATED/MIGHT_COOK/... enum → TierBadge number.
function tierNumber(walletTier?: string | null): number | null {
  if (!walletTier) return null;
  const t = walletTier.toUpperCase();
  if (t === "CURATED") return 2;
  if (t === "GLOBAL" || t === "LEADERBOARD") return 1;
  return null;
}

// Size bucket (distinct from wallet quality) for filtering by trade/deposit size.
const SIZE_BUCKETS = [
  { value: "all", label: "Any size" },
  { value: "Tier 4", label: "$100k+" },
  { value: "Tier 3", label: "$50k+" },
  { value: "Tier 2", label: "$20k+" },
  { value: "Tier 1", label: "$5k+" },
];

interface Alert {
  id: number;
  address: string;
  alert_type: "LARGE_TRADE" | "LARGE_DEPOSIT";
  amount_usdc: number;
  transaction_hash: string;
  condition_id?: string;
  outcome?: string | null;
  market_title?: string | null;
  category?: string | null;
  subcategory?: string | null;
  wallet_name?: string | null;
  wallet_tier?: string | null;
  created_at: string;
  wallet_stats?: { balance?: number | null; position_value?: number | null };
}

interface Summary {
  live_events: number;
  trades: number;
  deposits: number;
  deposit_inflow: number;
  biggest: { amount: number; address: string | null; wallet_name: string | null };
}

const PAGE_SIZE = 50;

export default function AlphaFeedPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabKey>("all");
  const [sizeBucket, setSizeBucket] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [watchlistStatus, setWatchlistStatus] = useState<Record<string, "idle" | "loading" | "success">>({});

  useEffect(() => {
    getAlphaCallsSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function fetchData() {
      setLoading(true);
      try {
        // "all" fetches without an alert_type filter; specific tabs pass the type.
        const alertType = tab === "trades" ? "LARGE_TRADE" : tab === "deposits" ? "LARGE_DEPOSIT" : undefined;
        const res = await getSmartMoneyAlerts(
          PAGE_SIZE,
          (page - 1) * PAGE_SIZE,
          alertType,
          sizeBucket,
        );
        if (cancelled) return;
        setAlerts(res?.alerts || []);
        setTotalCount(res?.total_count || 0);
      } catch (e) {
        if (!cancelled) console.error("Failed to fetch alpha feed", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [tab, sizeBucket, page]);

  const handleCopy = (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  const handleAddToWatchlist = async (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    try {
      setWatchlistStatus((p) => ({ ...p, [address]: "loading" }));
      await toggleWatchlist(address, "add");
      setWatchlistStatus((p) => ({ ...p, [address]: "success" }));
      setTimeout(() => setWatchlistStatus((p) => ({ ...p, [address]: "idle" })), 3000);
    } catch (error) {
      console.error("Failed to add to watchlist", error);
      setWatchlistStatus((p) => ({ ...p, [address]: "idle" }));
    }
  };

  const filtered = alerts.filter(
    (a) => !searchQuery || (a.address || "").toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const tabs = [
    { key: "all", label: "All", count: summary?.live_events ?? null },
    { key: "trades", label: "Trades", count: summary?.trades ?? null },
    { key: "deposits", label: "Deposits", count: summary?.deposits ?? null },
  ] as const;

  return (
    <div className="max-w-[1400px] mx-auto">
      {/* Stat cards */}
      <StatCardRow>
        <StatCard
          label="Live events"
          icon={<Radio size={16} />}
          value={summary?.live_events ?? "—"}
          subtitle="Trades + deposits over $5K"
        />
        <StatCard
          label="Large trades"
          icon={<ArrowLeftRight size={16} />}
          value={summary?.trades ?? "—"}
          subtitle="Grouped partial fills"
        />
        <StatCard
          label="Large deposits"
          icon={<ArrowDownToLine size={16} />}
          value={summary?.deposits ?? "—"}
          subtitle={summary ? `${formatCurrency(summary.deposit_inflow)} inbound` : undefined}
        />
        <StatCard
          label="Biggest signal"
          icon={<Flame size={16} />}
          value={summary ? formatCurrency(summary.biggest.amount) : "—"}
          valueClassName="text-signal"
          subtitle={summary?.biggest.wallet_name || summary?.biggest.address ? (
            <span className="font-mono">
              {summary.biggest.wallet_name || formatAddress(summary.biggest.address || "")}
            </span>
          ) : undefined}
        />
      </StatCardRow>

      {/* Tabs + filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <PillTabs tabs={tabs} active={tab} onChange={(k) => { setTab(k as TabKey); setPage(1); }} />
        <div className="ml-auto flex items-center gap-2">
          <select
            className="bg-surface border border-border rounded-lg px-2.5 py-1.5 text-xs outline-none focus:border-primary text-foreground cursor-pointer"
            value={sizeBucket}
            onChange={(e) => { setSizeBucket(e.target.value); setPage(1); }}
          >
            {SIZE_BUCKETS.map((b) => (
              <option key={b.value} value={b.value}>{b.label}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Search wallet…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-surface border border-border rounded-lg px-3 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder-subtle w-40 font-mono"
          />
        </div>
      </div>

      <p className="text-xs text-subtle mb-3">
        Every live signal picked up by the scanners — trades and deposits above $5,000.
      </p>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse min-w-[1000px]">
            <thead>
              <tr className="border-b border-border bg-surface text-xs text-subtle font-mono uppercase tracking-wider">
                <th className="py-3 px-4 font-semibold w-24">Type</th>
                <th className="py-3 px-4 font-semibold">Wallet</th>
                <th className="py-3 px-4 font-semibold w-24">Tier</th>
                <th className="py-3 px-4 font-semibold">Market</th>
                <th className="py-3 px-4 font-semibold text-right w-28">Amount</th>
                <th className="py-3 px-4 font-semibold text-right w-28">Balance</th>
                <th className="py-3 px-4 font-semibold w-28">Tx</th>
                <th className="py-3 px-4 font-semibold text-right w-24">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center">
                    <div className="inline-block animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8}>
                    <EmptyState icon={<Radio size={22} />} title="No activity matches the current filters." />
                  </td>
                </tr>
              ) : (
                filtered.map((a) => {
                  const isDeposit = a.alert_type === "LARGE_DEPOSIT";
                  const t = timeAgo(a.created_at);
                  return (
                    <tr key={`${a.id}-${a.transaction_hash}`} className="hover:bg-surface-2/40 transition-colors group">
                      <td className="py-3 px-4">
                        <TypeBadge kind={isDeposit ? "deposit" : "trade"} />
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <Avatar name={a.wallet_name} address={a.address} size={26} />
                          <div className="min-w-0">
                            <Link
                              href={`/wallet/${a.address}`}
                              className="text-sm font-medium text-foreground hover:text-primary transition-colors block truncate max-w-[140px]"
                            >
                              {a.wallet_name || formatAddress(a.address)}
                            </Link>
                            <button
                              onClick={(e) => handleCopy(e, a.address)}
                              className="text-[11px] font-mono text-subtle hover:text-foreground transition-colors flex items-center gap-1"
                              title="Copy address"
                            >
                              {formatAddress(a.address)}
                              {copiedAddress === a.address ? <Check size={10} className="text-primary" /> : <Copy size={10} />}
                            </button>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <TierBadge tier={tierNumber(a.wallet_tier)} />
                      </td>
                      <td className="py-3 px-4 max-w-[280px]">
                        {isDeposit ? (
                          <span className="text-sm text-subtle">USDC deposit</span>
                        ) : (
                          <div className="min-w-0">
                            <div className="text-sm text-foreground truncate" title={a.market_title || ""}>
                              {a.market_title || "—"}
                            </div>
                            {a.outcome && (
                              <div className="text-[11px] text-subtle">{a.outcome}</div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-bold text-foreground">
                        {formatCurrency(a.amount_usdc)}
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-muted-fg">
                        {a.wallet_stats?.balance ? formatCurrency(a.wallet_stats.balance) : "—"}
                      </td>
                      <td className="py-3 px-4">
                        <a
                          href={`https://polygonscan.com/tx/${a.transaction_hash}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] font-mono text-primary/70 hover:text-primary transition-colors"
                          title={a.transaction_hash}
                        >
                          {a.transaction_hash ? `${a.transaction_hash.slice(0, 6)}…${a.transaction_hash.slice(-4)}` : "—"}
                        </a>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-[11px] text-subtle whitespace-nowrap" title={t?.absolute}>
                            {t?.relative}
                          </span>
                          <button
                            onClick={(e) => handleAddToWatchlist(e, a.address)}
                            disabled={watchlistStatus[a.address] === "loading" || watchlistStatus[a.address] === "success"}
                            className="p-1 rounded text-subtle hover:text-foreground opacity-0 group-hover:opacity-100 transition-all disabled:opacity-50"
                            title="Add to watchlist"
                          >
                            {watchlistStatus[a.address] === "success" ? (
                              <Check size={13} className="text-primary opacity-100" />
                            ) : (
                              <PlusCircle size={13} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex justify-center items-center gap-2 py-4">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="px-3 py-1 bg-surface border border-border hover:bg-surface-2 transition-colors rounded-lg text-xs text-foreground disabled:opacity-40 cursor-pointer"
        >
          Previous
        </button>
        <span className="text-xs text-subtle mx-2">Page {page} of {totalPages}</span>
        <button
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
          className="px-3 py-1 bg-surface border border-border hover:bg-surface-2 transition-colors rounded-lg text-xs text-foreground disabled:opacity-40 cursor-pointer"
        >
          Next
        </button>
      </div>
    </div>
  );
}
