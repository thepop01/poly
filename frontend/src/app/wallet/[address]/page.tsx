"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getWalletStats, getWalletTrades, getWalletPositions } from "@/utils/api";
import { formatCurrency } from "@/utils/format";
import Link from "next/link";
import { ArrowLeft, ExternalLink, Copy, Check } from "lucide-react";

import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";
import { LikeButton } from "@/components/ui/LikeButton";
import { getWatchlistCounts } from "@/utils/api";

export default function WalletPage() {
  const params = useParams();
  const address = params?.address as string;
  const { isLiked, toggleLike } = useFavoriteToggle(address ? [address] : []);
  const [favoriteCount, setFavoriteCount] = useState<number>(0);
  const [stats, setStats] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"positions" | "trades" | "closed">("positions");
  const [closedPositions, setClosedPositions] = useState<any[]>([]);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!address) return;
    getWatchlistCounts([address]).then((res) => {
      if (res?.counts && res.counts[address.toLowerCase()] != null) {
        setFavoriteCount(res.counts[address.toLowerCase()]);
      }
    }).catch(() => {});
  }, [address]);

  const handleToggle = (e: React.MouseEvent) => {
    const currentlyLiked = isLiked(address);
    setFavoriteCount((prev) => (currentlyLiked ? Math.max(0, prev - 1) : prev + 1));
    toggleLike(address, e);
  };

  useEffect(() => {
    if (!address) return;
    async function fetch() {
      setLoading(true);
      try {
        const [s, t, p] = await Promise.all([
          getWalletStats(address),
          getWalletTrades(address, 100),
          getWalletPositions(address),
        ]);
        setStats(s);
        setTrades(t || []);
        setPositions(p || []);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    fetch();
  }, [address]);

  useEffect(() => {
    if (activeTab === "closed" && address) {
      fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/v2/wallets/${address}/closed-positions?limit=100`)
        .then(r => r.json())
        .then(d => setClosedPositions(Array.isArray(d) ? d : []))
        .catch(() => {});
    }
  }, [activeTab, address]);

  if (!address) return null;

  return (
    <div className="w-full h-full flex flex-col bg-background">
      <div className="flex items-center gap-4 mb-4 flex-shrink-0">
        <Link href="/wallets" className="text-muted-fg hover:text-foreground transition-colors">
          <ArrowLeft size={18} />
        </Link>
        <h1 className="text-lg font-bold text-foreground flex items-center gap-2">
          <span className="font-mono text-primary">
            {address.slice(0, 8)}...{address.slice(-6)}
          </span>
          <button
            onClick={() => { navigator.clipboard.writeText(address); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
            className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground"
          >
            {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
          </button>
          <a href={`https://polygonscan.com/address/${address}`} target="_blank" rel="noreferrer" className="text-[10px] text-[#0EA5E9] hover:underline ml-2">
            POLYGONSCAN <ExternalLink size={10} className="inline" />
          </a>
          <LikeButton
            isLiked={isLiked(address)}
            onToggle={handleToggle}
            favoriteCount={favoriteCount}
            size={18}
          />
        </h1>
      </div>

      {loading ? (
        <div className="flex items-center justify-center flex-1">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
        </div>
      ) : (
        <>
          {/* Stats cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 flex-shrink-0">
            {[
              { label: "PnL", value: formatCurrency(stats?.total_pnl || 0), color: (stats?.total_pnl || 0) >= 0 ? "text-green-500" : "text-red-500" },
              { label: "Volume", value: formatCurrency(stats?.total_volume || 0), color: "text-foreground" },
              { label: "Win Rate", value: `${((stats?.win_rate || 0) * 100).toFixed(1)}%`, color: "text-foreground" },
              { label: "ROI", value: `${(stats?.roi_pct || 0) > 0 ? "+" : ""}${(stats?.roi_pct || 0).toFixed(2)}%`, color: (stats?.roi_pct || 0) >= 0 ? "text-green-500" : "text-red-500" },
            ].map((card, i) => (
              <div key={i} className="bg-surface border border-border rounded-lg p-3">
                <div className="text-[10px] text-muted-fg uppercase mb-1">{card.label}</div>
                <div className={`text-sm font-mono font-bold ${card.color}`}>{card.value}</div>
              </div>
            ))}
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-3 flex-shrink-0">
            {(["positions", "trades", "closed"] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors capitalize ${
                  activeTab === tab ? "bg-primary/10 text-primary border border-primary/20" : "text-muted-fg hover:text-foreground"
                }`}
              >
                {tab === "closed" ? "Closed Positions" : tab}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto bg-surface border border-border rounded-lg">
            {activeTab === "positions" && (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-2/50 text-muted-fg uppercase tracking-wider">
                  <tr>
                    <th className="py-2 px-3 text-left">Market</th>
                    <th className="py-2 px-3 text-right">Side</th>
                    <th className="py-2 px-3 text-right">Size</th>
                    <th className="py-2 px-3 text-right">Price</th>
                    <th className="py-2 px-3 text-right">Value</th>
                    <th className="py-2 px-3 text-right">P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {positions.length === 0 ? (
                    <tr><td colSpan={6} className="py-8 text-center text-muted-fg">No open positions</td></tr>
                  ) : (
                    positions.map((p, i) => (
                      <tr key={i} className="hover:bg-surface-2/20">
                        <td className="py-2 px-3 truncate max-w-[200px]">{p.title || p.market_title || "—"}</td>
                        <td className={`py-2 px-3 text-right ${p.side?.toUpperCase() === 'YES' ? 'text-green-500' : 'text-red-500'}`}>{p.side || p.outcome || "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{p.totalBought ? Number(p.totalBought).toFixed(2) : "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{p.avgPrice ? `${(Number(p.avgPrice) * 100).toFixed(1)}¢` : "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{p.currentValue ? formatCurrency(Number(p.currentValue)) : "—"}</td>
                        <td className={`py-2 px-3 text-right font-mono ${Number(p.cashPnl || 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                          {p.cashPnl ? formatCurrency(Number(p.cashPnl)) : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}

            {activeTab === "trades" && (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-2/50 text-muted-fg uppercase tracking-wider">
                  <tr>
                    <th className="py-2 px-3 text-left">Market</th>
                    <th className="py-2 px-3 text-right">Side</th>
                    <th className="py-2 px-3 text-right">Size</th>
                    <th className="py-2 px-3 text-right">Price</th>
                    <th className="py-2 px-3 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {trades.length === 0 ? (
                    <tr><td colSpan={5} className="py-8 text-center text-muted-fg">No trades found</td></tr>
                  ) : (
                    trades.map((t, i) => (
                      <tr key={i} className="hover:bg-surface-2/20">
                        <td className="py-2 px-3 truncate max-w-[200px]">{t.title || t.market_title || "—"}</td>
                        <td className={`py-2 px-3 text-right ${t.side?.toUpperCase() === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>{t.side || "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{t.size ? Number(t.size).toFixed(2) : "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{t.price ? `${(Number(t.price) * 100).toFixed(1)}¢` : "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{formatCurrency(Number(t.size || 0) * Number(t.price || 0))}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}

            {activeTab === "closed" && (
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-2/50 text-muted-fg uppercase tracking-wider">
                  <tr>
                    <th className="py-2 px-3 text-left">Market</th>
                    <th className="py-2 px-3 text-right">Outcome</th>
                    <th className="py-2 px-3 text-right">Avg Price</th>
                    <th className="py-2 px-3 text-right">Bought</th>
                    <th className="py-2 px-3 text-right">Realized PnL</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {closedPositions.length === 0 ? (
                    <tr><td colSpan={5} className="py-8 text-center text-muted-fg">No closed positions</td></tr>
                  ) : (
                    closedPositions.map((cp, i) => (
                      <tr key={i} className="hover:bg-surface-2/20">
                        <td className="py-2 px-3 truncate max-w-[200px]">{cp.title || "—"}</td>
                        <td className={`py-2 px-3 text-right ${cp.outcome?.toUpperCase() === 'YES' ? 'text-green-500' : 'text-red-500'}`}>{cp.outcome || "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{cp.avgPrice ? `${(Number(cp.avgPrice) * 100).toFixed(1)}¢` : "—"}</td>
                        <td className="py-2 px-3 text-right font-mono">{cp.totalBought ? Number(cp.totalBought).toFixed(2) : "—"}</td>
                        <td className={`py-2 px-3 text-right font-mono ${Number(cp.realizedPnl || 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                          {cp.realizedPnl ? formatCurrency(Number(cp.realizedPnl)) : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
