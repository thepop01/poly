"use client";

import { useEffect, useState } from "react";
import { getWatchlist, toggleWatchlist, toggleWalletAlert } from "@/utils/api";
import { formatCurrency } from "@/utils/format";
import Link from "next/link";
import { Anchor, Copy, Check, Trash2, Bell, BellOff, ArrowRight, Plus, Loader2 } from "lucide-react";

interface WatchlistEntry {
  address: string;
  win_rate: number | null;
  roi_pct: number | null;
  total_volume: string;
  total_pnl?: string;
  alerts_enabled: boolean;
}

export default function WalletTrackerPage() {
  const [data, setData] = useState<WatchlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [newWallet, setNewWallet] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  useEffect(() => {
    fetchData();
  }, []);

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const res = await getWatchlist();
      setData(res);
    } catch (e: any) {
      console.error("Failed to fetch watchlist", e);
      if (e.message?.includes("401")) {
        setError("Please log in to view your Wallet Tracker.");
      } else {
        setError("Failed to load watchlist.");
      }
    } finally {
      setLoading(false);
    }
  }

  const formatAddress = (addr: string) => {
    if (!addr) return "Unknown";
    if (addr.length < 10) return addr;
    return `${addr.slice(0, 5)}...${addr.slice(-4)}`;
  };

  const handleCopy = (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  const handleRemove = async (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    if (!confirm("Remove this wallet from your watchlist?")) return;
    try {
      await toggleWatchlist(address, 'remove');
      setData(data.filter(d => d.address !== address));
    } catch (error) {
      console.error("Failed to remove from watchlist", error);
      alert("Failed to remove wallet.");
    }
  };

  const handleToggleAlert = async (e: React.MouseEvent, address: string, currentStatus: boolean) => {
    e.preventDefault();
    try {
      await toggleWalletAlert(address, !currentStatus);
      setData(data.map(d => d.address === address ? { ...d, alerts_enabled: !currentStatus } : d));
    } catch (error) {
      console.error("Failed to toggle alert", error);
      alert("Failed to toggle alerts.");
    }
  };

  const handleAddWallet = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWallet.trim()) return;
    
    setIsAdding(true);
    try {
      await toggleWatchlist(newWallet.trim(), 'add');
      setNewWallet("");
      fetchData(); // Refresh the list
    } catch (err: any) {
      console.error("Failed to add wallet", err);
      alert(err.message || "Failed to add wallet.");
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="w-full h-full flex flex-col bg-background">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Anchor className="text-primary w-5 h-5" /> Wallet Tracker
        </h1>
        
        <form onSubmit={handleAddWallet} className="flex items-center gap-2">
          <input 
            type="text" 
            placeholder="0x..." 
            value={newWallet}
            onChange={(e) => setNewWallet(e.target.value)}
            className="px-3 py-1.5 text-sm bg-surface-2 border border-border rounded-lg text-foreground focus:outline-none focus:border-primary placeholder:text-muted-fg w-64 font-mono"
          />
          <button 
            type="submit" 
            disabled={isAdding || !newWallet.trim()}
            className="flex items-center justify-center gap-1.5 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isAdding ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            <span>Add</span>
          </button>
        </form>
      </div>

      {/* Table */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden flex-1 min-h-0 flex flex-col shadow-sm">
        <div className="overflow-x-auto overflow-y-auto flex-1 relative">
          <table className="w-full text-left text-sm border-collapse min-w-[800px]">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-surface-2/40 text-muted-fg font-mono uppercase tracking-wider text-xs">
                <th className="py-3 px-4 font-semibold w-16 text-center">Status</th>
                <th className="py-3 px-4 font-semibold">Wallet</th>
                <th className="py-3 px-4 font-semibold text-right">Volume</th>
                <th className="py-3 px-4 font-semibold text-right">Win Rate</th>
                <th className="py-3 px-4 font-semibold text-right">ROI</th>
                <th className="py-3 px-4 font-semibold text-right">Profit</th>
                <th className="py-3 px-4 font-semibold text-center w-24">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center">
                    <div className="inline-block animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-muted-fg font-mono text-sm">
                    <span className="text-red-500 mb-2 block font-semibold">{error}</span>
                    To mock a login locally, append `?token=YOUR_MOCK_TOKEN` to the URL.
                  </td>
                </tr>
              ) : data.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-muted-fg font-mono text-sm">
                    You are not tracking any wallets yet. 
                    <br />
                    <Link href="/leaderboard" className="inline-flex items-center gap-2 mt-4 text-primary hover:underline">
                      Find wallets on the Leaderboard <ArrowRight size={14} />
                    </Link>
                  </td>
                </tr>
              ) : (
                data.map((entry) => {
                  const pnlVal = parseFloat(entry.total_pnl || "0");
                  const volVal = parseFloat(entry.total_volume || "0");
                  const roiVal = parseFloat(String(entry.roi_pct || 0));
                  const winRateVal = parseFloat(String(entry.win_rate || 0)) * 100;

                  return (
                    <tr
                      key={entry.address}
                      className="hover:bg-surface-2/20 transition-colors group cursor-default"
                    >
                      <td className="py-2.5 px-4 text-center">
                        <button
                          onClick={(e) => handleToggleAlert(e, entry.address, entry.alerts_enabled)}
                          className={`p-1.5 rounded transition-colors ${entry.alerts_enabled ? 'text-primary bg-primary/10 hover:bg-primary/20' : 'text-muted-fg bg-surface-2 hover:bg-surface-2/80'}`}
                          title={entry.alerts_enabled ? "Alerts Enabled" : "Alerts Disabled"}
                        >
                          {entry.alerts_enabled ? <Bell size={14} /> : <BellOff size={14} />}
                        </button>
                      </td>
                      <td className="py-2.5 px-4 font-medium text-foreground flex items-center gap-2">
                        <Link href={`/wallet/${entry.address}`} className="hover:text-primary transition-colors font-mono bg-primary/5 px-2 py-0.5 rounded border border-primary/10">
                          {formatAddress(entry.address)}
                        </Link>
                        <button
                          onClick={(e) => handleCopy(e, entry.address)}
                          className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors"
                          title="Copy Address"
                        >
                          {copiedAddress === entry.address ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                        </button>
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono font-medium text-foreground whitespace-nowrap">
                        {formatCurrency(volVal)}
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono font-medium text-foreground whitespace-nowrap">
                        {winRateVal.toFixed(1)}%
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono font-medium whitespace-nowrap">
                        <span className={roiVal >= 0 ? "text-green-500" : "text-red-500"}>
                          {roiVal > 0 ? "+" : ""}{roiVal.toFixed(2)}%
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono font-medium text-foreground whitespace-nowrap">
                        <span className={pnlVal >= 0 ? "text-green-500 font-bold" : "text-red-500 font-bold"}>
                          {pnlVal > 0 ? "+" : ""}
                          {formatCurrency(pnlVal)}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <button
                          onClick={(e) => handleRemove(e, entry.address)}
                          className="p-1.5 rounded text-red-500/70 hover:text-red-500 hover:bg-red-500/10 transition-colors inline-flex items-center justify-center"
                          title="Remove from Watchlist"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
