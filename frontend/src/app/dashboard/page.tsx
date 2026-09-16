"use client";

import { useEffect, useMemo, useState } from "react";
import { Wallet, Cpu, Zap, Crown } from "lucide-react";
import { getWatchlist, getSmartMoneyAlerts, listAgents, listNotifications } from "@/utils/api";
import { useAuth } from "@/components/AuthProvider";
import { formatSignedCurrency, formatCurrency, toNum } from "@/utils/format";
import { StatCard, StatCardRow } from "@/components/ui/StatCard";
import { PillTabs } from "@/components/ui/PillTabs";
import { WatchlistSnapshot, WatchlistEntry } from "./WatchlistSnapshot";
import { AlphaCallsSnapshot, AlphaSnapshotItem } from "./AlphaCallsSnapshot";
import { AddWalletsPanel } from "./AddWalletsPanel";
import { TrackedWalletsTab } from "@/components/dashboard/TrackedWalletsTab";
import { WalletAlertsCard } from "@/components/dashboard/WalletAlertsCard";

type TabKey = "overview" | "watchlist" | "agents";

export default function DashboardPage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<TabKey>("overview");
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [feed, setFeed] = useState<AlphaSnapshotItem[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [runsToday, setRunsToday] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        // Public feed always loads; watchlist/agents require auth.
        const feedPromise = getSmartMoneyAlerts(5, 0).catch(() => null);
        const watchlistPromise = token ? getWatchlist().catch(() => []) : Promise.resolve([]);
        const agentsPromise = token ? listAgents().catch(() => null) : Promise.resolve(null);
        const notifsPromise = token ? listNotifications().catch(() => null) : Promise.resolve(null);

        const [feedRes, wl, agentsRes, notifsRes] = await Promise.all([
          feedPromise,
          watchlistPromise,
          agentsPromise,
          notifsPromise,
        ]);
        if (cancelled) return;

        // Watchlist rows come from wallets_v2 join
        const wlRows: WatchlistEntry[] = (Array.isArray(wl) ? wl : []).map((r: any) => ({
          address: r.address || r.wallet_address,
          username: r.username,
          pnl: r.pnl ?? r.website_pnl,
          balance: r.balance,
        }));
        wlRows.sort((a, b) => (toNum(b.pnl) ?? 0) - (toNum(a.pnl) ?? 0));
        setWatchlist(wlRows);

        const alerts = feedRes?.alerts || [];
        setFeed(
          alerts.slice(0, 5).map((a: any) => ({
            id: `${a.alert_type}-${a.transaction_hash}`,
            type: a.alert_type === "LARGE_DEPOSIT" ? "deposit" : "trade",
            address: a.address,
            username: a.wallet_name,
            market_title: a.market_title,
            amount: a.amount_usdc != null ? Number(a.amount_usdc) : null,
            timestamp: a.created_at,
          }))
        );

        setAgents(agentsRes?.agents || []);
        setRunsToday(notifsRes?.notifications?.length || 0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const combinedPnl = useMemo(
    () => watchlist.reduce((sum, w) => sum + (toNum(w.pnl) ?? 0), 0),
    [watchlist]
  );
  const activeAgents = useMemo(() => agents.filter((a) => a.is_active).length, [agents]);
  const topPerformer = watchlist[0];

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "watchlist", label: "Tracked Wallets", count: watchlist.length },
    { key: "agents", label: "Agents", count: agents.length },
  ] as const;

  return (
    <div className="max-w-7xl mx-auto">
      <div className="mb-6">
        <PillTabs tabs={tabs} active={tab} onChange={(k) => setTab(k as TabKey)} />
      </div>

      {tab === "overview" && (
        <>
          <StatCardRow>
            <StatCard
              label="Tracked wallets"
              icon={<Wallet size={16} />}
              value={loading ? "—" : watchlist.length}
              subtitle={
                <span className={combinedPnl >= 0 ? "text-primary" : "text-danger"}>
                  {formatSignedCurrency(combinedPnl)} combined PnL
                </span>
              }
            />
            <StatCard
              label="Active agents"
              icon={<Cpu size={16} />}
              value={loading ? "—" : activeAgents}
              subtitle={`${runsToday} runs today`}
            />
            <StatCard
              label="Alpha signals"
              icon={<Zap size={16} />}
              value={loading ? "—" : feed.length}
              subtitle="In the latest feed window"
            />
            <StatCard
              label="Top performer"
              icon={<Crown size={16} />}
              value={
                <span className="text-lg">
                  {topPerformer ? topPerformer.username || "Wallet" : "—"}
                </span>
              }
              valueClassName="text-foreground"
              subtitle={
                topPerformer ? (
                  <span className="text-primary">{formatSignedCurrency(topPerformer.pnl)} PnL</span>
                ) : (
                  "No watchlist yet"
                )
              }
            />
          </StatCardRow>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div className="lg:col-span-4">
              <AlphaCallsSnapshot items={feed} />
            </div>
            <div className="lg:col-span-4">
              <WalletAlertsCard />
            </div>
            <div className="lg:col-span-4">
              <AddWalletsPanel />
            </div>
          </div>
        </>
      )}

      {tab === "watchlist" && <TrackedWalletsTab />}

      {tab === "agents" && (
        <div className="card p-5">
          {agents.length === 0 ? (
            <div className="py-8 text-center text-sm text-subtle">
              No agents yet.{" "}
              <a href="/agents" className="text-primary hover:underline">
                Create one →
              </a>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {agents.map((a) => (
                <div key={a.id} className="flex items-center justify-between py-3 first:pt-0">
                  <div>
                    <div className="text-sm font-medium text-foreground">{a.name}</div>
                    <div className="text-xs text-subtle">{a.description || "—"}</div>
                  </div>
                  <span
                    className={`badge ${a.is_active ? "badge-success" : "badge-muted"}`}
                  >
                    {a.is_active ? "Active" : "Paused"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
