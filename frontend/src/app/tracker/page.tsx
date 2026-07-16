"use client";

import { useEffect, useState, useCallback } from "react";
import { getTrackerLists, getTrackerListWallets, createTrackerList, deleteTrackerList, addWalletToTrackerList, removeWalletFromTrackerList } from "@/utils/api";
import Link from "next/link";
import { Anchor, Plus, Trash2, X } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";

interface TrackerList {
  id: number;
  name: string;
  created_at: string;
  wallet_count: number;
}

interface TrackerWallet {
  wallet_address: string;
  note: string | null;
  added_at: string;
  username: string | null;
  website_pnl: number | null;
  win_rate: number | null;
  roi_pct: number | null;
  resolved_count: number | null;
  is_dormant: boolean;
  last_trade_at: string | null;
  category: string | null;
  subcategory: string | null;
}

function formatAddress(addr: string) {
  if (!addr) return "Unknown";
  if (addr.length < 10) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

export default function TrackerPage() {
  const { token } = useAuth();
  const [lists, setLists] = useState<TrackerList[]>([]);
  const [selectedListId, setSelectedListId] = useState<number | null>(null);
  const [wallets, setWallets] = useState<TrackerWallet[]>([]);
  const [loading, setLoading] = useState(true);
  const [newListName, setNewListName] = useState("");
  const [showNewList, setShowNewList] = useState(false);
  const [addWalletAddr, setAddWalletAddr] = useState("");
  const [addWalletNote, setAddWalletNote] = useState("");
  const [showAddWallet, setShowAddWallet] = useState(false);

  const fetchLists = useCallback(async () => {
    if (!token) { setLoading(false); return; }
    try {
      const data = await getTrackerLists();
      setLists(data.lists || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [token]);

  const fetchWallets = useCallback(async () => {
    if (!selectedListId) return;
    try {
      const data = await getTrackerListWallets(selectedListId);
      setWallets(data.wallets || []);
    } catch (e) {
      console.error(e);
    }
  }, [selectedListId]);

  useEffect(() => { fetchLists(); }, [fetchLists]);
  useEffect(() => { fetchWallets(); }, [fetchWallets]);

  const handleCreateList = async () => {
    if (!newListName.trim()) return;
    try {
      await createTrackerList(newListName.trim());
      setNewListName("");
      setShowNewList(false);
      fetchLists();
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteList = async (id: number) => {
    try {
      await deleteTrackerList(id);
      if (selectedListId === id) {
        setSelectedListId(null);
        setWallets([]);
      }
      fetchLists();
    } catch (e) {
      console.error(e);
    }
  };

  const handleAddWallet = async () => {
    if (!addWalletAddr.trim() || !selectedListId) return;
    try {
      await addWalletToTrackerList(selectedListId, addWalletAddr.trim(), addWalletNote.trim());
      setAddWalletAddr("");
      setAddWalletNote("");
      setShowAddWallet(false);
      fetchWallets();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveWallet = async (addr: string) => {
    if (!selectedListId) return;
    try {
      await removeWalletFromTrackerList(selectedListId, addr);
      fetchWallets();
    } catch (e) {
      console.error(e);
    }
  };

  if (!token) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-center">
          <Anchor className="w-12 h-12 text-muted-fg mx-auto mb-4" />
          <h2 className="text-xl font-bold mb-2">Login Required</h2>
          <p className="text-sm text-muted-fg">Connect your wallet or login with Discord to use My Tracker.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex gap-4">
      {/* Left panel - list selector */}
      <div className="w-56 flex-shrink-0 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-foreground">My Lists</h2>
          <button
            onClick={() => setShowNewList(true)}
            className="p-1 rounded-lg hover:bg-surface-2 text-muted-fg hover:text-foreground transition"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-0.5">
          {lists.map((list) => (
            <div key={list.id} className="flex items-center gap-1">
              <button
                onClick={() => setSelectedListId(list.id)}
                className={`flex-1 flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition text-left ${selectedListId === list.id
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-fg hover:text-foreground hover:bg-surface-2 border border-transparent"
                  }`}
              >
                <span className="truncate">{list.name}</span>
                <span className="text-[10px] opacity-60">{list.wallet_count}</span>
              </button>
              <button
                onClick={() => handleDeleteList(list.id)}
                className="p-1 rounded hover:bg-surface-2 text-muted-fg hover:text-danger transition opacity-0 hover:opacity-100"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}

          {showNewList && (
            <div className="flex items-center gap-1 px-2">
              <input
                type="text"
                placeholder="List name..."
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateList()}
                className="flex-1 px-2 py-1 rounded bg-surface-2 border border-border text-xs focus:border-primary focus:outline-none"
                autoFocus
              />
              <button onClick={handleCreateList} className="p-1 text-primary hover:opacity-80">
                <Plus className="w-3 h-3" />
              </button>
              <button onClick={() => setShowNewList(false)} className="p-1 text-muted-fg hover:text-foreground">
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Right panel - wallets in selected list */}
      <div className="flex-1 flex flex-col gap-3">
        {selectedListId ? (
          <>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-foreground">
                {lists.find((l) => l.id === selectedListId)?.name || "List"}
              </h2>
              <button
                onClick={() => setShowAddWallet(true)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary/10 text-primary border border-primary/20 text-xs font-medium hover:bg-primary/20 transition"
              >
                <Plus className="w-3 h-3" />
                Add Wallet
              </button>
            </div>

            {showAddWallet && (
              <div className="flex items-center gap-2 p-3 bg-surface-2 rounded-lg border border-border">
                <input
                  type="text"
                  placeholder="Wallet address (0x...)"
                  value={addWalletAddr}
                  onChange={(e) => setAddWalletAddr(e.target.value)}
                  className="flex-1 px-3 py-1.5 rounded bg-surface border border-border text-sm font-mono focus:border-primary focus:outline-none"
                />
                <input
                  type="text"
                  placeholder="Note (optional)"
                  value={addWalletNote}
                  onChange={(e) => setAddWalletNote(e.target.value)}
                  className="w-40 px-3 py-1.5 rounded bg-surface border border-border text-sm focus:border-primary focus:outline-none"
                />
                <button
                  onClick={handleAddWallet}
                  className="px-3 py-1.5 rounded-lg bg-primary text-surface text-xs font-bold hover:opacity-90 transition"
                >
                  Add
                </button>
                <button
                  onClick={() => setShowAddWallet(false)}
                  className="p-1.5 text-muted-fg hover:text-foreground"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            <div className="flex-1 overflow-auto bg-surface rounded-xl border border-border">
              {wallets.length === 0 ? (
                <div className="flex items-center justify-center h-full text-sm text-muted-fg">
                  No wallets in this list yet
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface-2 border-b border-border">
                    <tr className="text-left text-muted-fg">
                      <th className="px-4 py-3 font-medium text-xs">Wallet</th>
                      <th className="px-4 py-3 font-medium text-xs">Note</th>
                      <th className="px-4 py-3 font-medium text-xs">Category</th>
                      <th className="px-4 py-3 font-medium text-xs">PnL</th>
                      <th className="px-4 py-3 font-medium text-xs">Win%</th>
                      <th className="px-4 py-3 font-medium text-xs">ROI</th>
                      <th className="px-4 py-3 font-medium text-xs">Status</th>
                      <th className="px-4 py-3 font-medium text-xs">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallets.map((w) => (
                      <tr key={w.wallet_address} className="border-b border-border/50 hover:bg-surface-2 transition">
                        <td className="px-4 py-3">
                          <div className="font-mono text-xs text-foreground">
                            {formatAddress(w.wallet_address)}
                          </div>
                          {w.username && <div className="text-xs text-muted-fg">{w.username}</div>}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-fg max-w-32 truncate">
                          {w.note || "—"}
                        </td>
                        <td className="px-4 py-3 text-xs">
                          {w.category || "—"}
                          {w.subcategory && <div className="text-[10px] text-muted-fg">{w.subcategory}</div>}
                        </td>
                        <td className={`px-4 py-3 font-bold ${Number(w.website_pnl || 0) >= 0 ? "text-success" : "text-danger"}`}>
                          ${Number(w.website_pnl || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </td>
                        <td className="px-4 py-3">
                          {(Number(w.win_rate || 0) * 100).toFixed(0)}%
                        </td>
                        <td className="px-4 py-3">
                          {w.roi_pct ? `${Number(w.roi_pct).toFixed(1)}%` : "—"}
                        </td>
                        <td className="px-4 py-3">
                          {w.is_dormant ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-orange-500/10 text-orange-400">
                              Dormant
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-400">
                              Active
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 flex items-center gap-2">
                          <Link href={`/wallet/${w.wallet_address}`} className="text-primary hover:underline text-xs">
                            View
                          </Link>
                          <button
                            onClick={() => handleRemoveWallet(w.wallet_address)}
                            className="text-muted-fg hover:text-danger text-xs transition"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <Anchor className="w-12 h-12 text-muted-fg mx-auto mb-4" />
              <h2 className="text-lg font-bold mb-1">Select a list</h2>
              <p className="text-sm text-muted-fg">Choose a list from the left panel or create a new one</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
