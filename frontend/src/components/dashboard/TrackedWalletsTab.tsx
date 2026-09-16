"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Heart,
  FolderPlus,
  Trash2,
  Bell,
  Edit2,
  Plus,
  ChevronDown,
  ChevronUp,
  Folder,
  Check,
  X,
  UserCheck
} from "lucide-react";
import {
  getWatchlist,
  toggleWatchlist,
  toggleWalletAlert,
  getTrackerLists,
  createTrackerList,
  deleteTrackerList,
  renameTrackerList,
  getTrackerListWallets,
  addWalletToTrackerList,
  removeWalletFromTrackerList,
} from "@/utils/api";
import { formatCurrency, formatSignedCurrency, formatAddress, formatPercent } from "@/utils/format";
import { EmptyState } from "@/components/ui/EmptyState";
import { LikeButton } from "@/components/ui/LikeButton";

export interface TrackerGroup {
  id: number;
  name: string;
  created_at: string;
  wallet_count: number;
}

export function TrackedWalletsTab() {
  const [trackedWallets, setTrackedWallets] = useState<any[]>([]);
  const [groups, setGroups] = useState<TrackerGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [newGroupName, setNewGroupName] = useState("");
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [expandedGroupId, setExpandedGroupId] = useState<number | null>(null);
  const [groupWallets, setGroupWallets] = useState<Record<number, any[]>>({});
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [addingToGroupWallet, setAddingToGroupWallet] = useState<string | null>(null);

  const fetchTracked = async () => {
    try {
      const data = await getWatchlist();
      setTrackedWallets(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchGroups = async () => {
    try {
      const res = await getTrackerLists();
      if (res?.lists) {
        setGroups(res.lists);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchTracked(), fetchGroups()]).finally(() => setLoading(false));
  }, []);

  const handleToggleUnlike = async (address: string) => {
    setTrackedWallets((prev) => prev.filter((w) => w.address !== address));
    try {
      await toggleWatchlist(address);
    } catch (err) {
      fetchTracked();
    }
  };

  const handleToggleAlert = async (address: string, current: boolean) => {
    setTrackedWallets((prev) =>
      prev.map((w) => (w.address === address ? { ...w, alerts_enabled: !current } : w))
    );
    try {
      await toggleWalletAlert(address, !current);
    } catch (err) {
      fetchTracked();
    }
  };

  const handleCreateGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newGroupName.trim()) return;

    try {
      const res = await createTrackerList(newGroupName.trim());
      if (res?.list) {
        setNewGroupName("");
        setCreatingGroup(false);
        fetchGroups();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteGroup = async (id: number) => {
    try {
      await deleteTrackerList(id);
      setGroups((prev) => prev.filter((g) => g.id !== id));
      if (expandedGroupId === id) setExpandedGroupId(null);
    } catch (err) {
      console.error(err);
    }
  };

  const handleRenameGroup = async (id: number) => {
    if (!editingName.trim()) return;
    try {
      await renameTrackerList(id, editingName.trim());
      setEditingGroupId(null);
      fetchGroups();
    } catch (err) {
      console.error(err);
    }
  };

  const toggleExpandGroup = async (id: number) => {
    if (expandedGroupId === id) {
      setExpandedGroupId(null);
      return;
    }
    setExpandedGroupId(id);
    try {
      const res = await getTrackerListWallets(id);
      if (res?.wallets) {
        setGroupWallets((prev) => ({ ...prev, [id]: res.wallets }));
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAddWalletToGroup = async (groupId: number, walletAddress: string) => {
    try {
      await addWalletToTrackerList(groupId, walletAddress);
      setAddingToGroupWallet(null);
      fetchGroups();
      if (expandedGroupId === groupId) {
        toggleExpandGroup(groupId);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleRemoveWalletFromGroup = async (groupId: number, walletAddress: string) => {
    try {
      await removeWalletFromTrackerList(groupId, walletAddress);
      setGroupWallets((prev) => ({
        ...prev,
        [groupId]: (prev[groupId] || []).filter((w) => w.wallet_address !== walletAddress),
      }));
      fetchGroups();
    } catch (err) {
      console.error(err);
    }
  };

  if (loading) {
    return (
      <div className="card p-12 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-rose-500/10 flex items-center justify-center">
            <Heart size={20} className="text-rose-400 fill-rose-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-foreground">Tracked Wallets & Groups</h2>
            <p className="text-xs text-muted-fg mt-0.5">
              Organize your favorited smart money wallets into strategy groups.
            </p>
          </div>
        </div>

        <button
          onClick={() => setCreatingGroup(!creatingGroup)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-fg text-xs font-semibold rounded-lg hover:bg-primary/90 transition-colors shadow-xs"
        >
          <FolderPlus size={14} />
          Create Group
        </button>
      </div>

      {/* New Group Inline Modal */}
      {creatingGroup && (
        <form onSubmit={handleCreateGroup} className="card p-4 bg-surface-2/60 border border-primary/20 flex gap-3 items-center">
          <Folder className="text-primary flex-shrink-0" size={20} />
          <input
            type="text"
            placeholder="Group Name (e.g. Whales, Politics, High Winrate)..."
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
            className="flex-1 bg-background border border-border rounded-lg px-3 py-1.5 text-xs outline-none focus:border-primary text-foreground"
            autoFocus
          />
          <button
            type="submit"
            disabled={!newGroupName.trim()}
            className="px-3 py-1.5 bg-primary text-primary-fg text-xs font-bold rounded-lg disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => setCreatingGroup(false)}
            className="px-3 py-1.5 bg-surface border border-border text-muted-fg text-xs font-medium rounded-lg hover:text-foreground"
          >
            Cancel
          </button>
        </form>
      )}

      {/* GROUPS LIST */}
      {groups.length > 0 && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
            <Folder size={16} className="text-primary" />
            Wallet Groups ({groups.length})
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {groups.map((g) => {
              const isExpanded = expandedGroupId === g.id;
              const isEditing = editingGroupId === g.id;
              const walletsInGroup = groupWallets[g.id] || [];

              return (
                <div key={g.id} className="card p-3 flex flex-col gap-2 border border-border hover:border-primary/30 transition-colors">
                  <div className="flex items-center justify-between">
                    {isEditing ? (
                      <div className="flex items-center gap-1.5 flex-1">
                        <input
                          type="text"
                          value={editingName}
                          onChange={(e) => setEditingName(e.target.value)}
                          className="bg-background border border-border rounded px-2 py-0.5 text-xs font-bold text-foreground outline-none w-full"
                        />
                        <button onClick={() => handleRenameGroup(g.id)} className="text-green-500 hover:text-green-400">
                          <Check size={14} />
                        </button>
                        <button onClick={() => setEditingGroupId(null)} className="text-muted-fg hover:text-foreground">
                          <X size={14} />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 min-w-0">
                        <Folder size={16} className="text-primary flex-shrink-0" />
                        <span className="text-xs font-bold text-foreground truncate">{g.name}</span>
                        <span className="px-1.5 py-0.2 text-[10px] font-mono rounded bg-primary/10 text-primary border border-primary/20">
                          {g.wallet_count}
                        </span>
                      </div>
                    )}

                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => { setEditingGroupId(g.id); setEditingName(g.name); }}
                        className="p-1 text-muted-fg hover:text-foreground"
                        title="Rename Group"
                      >
                        <Edit2 size={12} />
                      </button>
                      <button
                        onClick={() => handleDeleteGroup(g.id)}
                        className="p-1 text-muted-fg hover:text-rose-500"
                        title="Delete Group"
                      >
                        <Trash2 size={12} />
                      </button>
                      <button
                        onClick={() => toggleExpandGroup(g.id)}
                        className="p-1 text-muted-fg hover:text-foreground"
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </div>
                  </div>

                  {/* Expanded Group Wallets */}
                  {isExpanded && (
                    <div className="mt-2 pt-2 border-t border-border flex flex-col gap-1.5">
                      {walletsInGroup.length === 0 ? (
                        <div className="text-[11px] text-muted-fg py-2 text-center">No wallets in this group yet.</div>
                      ) : (
                        walletsInGroup.map((w) => (
                          <div key={w.wallet_address} className="flex items-center justify-between text-xs py-1 px-2 rounded bg-surface-2/50">
                            <span className="font-mono text-foreground truncate">
                              {w.username || formatAddress(w.wallet_address)}
                            </span>
                            <button
                              onClick={() => handleRemoveWalletFromGroup(g.id, w.wallet_address)}
                              className="text-muted-fg hover:text-rose-500"
                              title="Remove from group"
                            >
                              <X size={12} />
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TRACKED WALLETS TABLE */}
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
          <UserCheck size={16} className="text-rose-400" />
          All Tracked Wallets ({trackedWallets.length})
        </h3>

        {trackedWallets.length === 0 ? (
          <EmptyState
            icon={<Heart size={24} />}
            title="No tracked wallets yet"
            hint="Click the heart icon on any leaderboard or wallet profile to track wallets here."
          />
        ) : (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm border-collapse min-w-[800px]">
                <thead>
                  <tr className="border-b border-border bg-surface text-xs text-subtle font-mono uppercase tracking-wider">
                    <th className="py-3 px-4 font-semibold w-12 text-center">#</th>
                    <th className="py-3 px-4 font-semibold">Wallet</th>
                    <th className="py-3 px-4 font-semibold text-right">PnL</th>
                    <th className="py-3 px-4 font-semibold text-right">Win%</th>
                    <th className="py-3 px-4 font-semibold text-right">Balance</th>
                    <th className="py-3 px-4 font-semibold text-center">Alerts</th>
                    <th className="py-3 px-4 font-semibold text-center">Add to Group</th>
                    <th className="py-3 px-4 font-semibold text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {trackedWallets.map((w, i) => (
                    <tr key={w.address} className="hover:bg-surface-2/40 transition-colors">
                      <td className="py-3 px-4 text-center font-mono text-xs text-muted-fg">{i + 1}</td>
                      <td className="py-3 px-4">
                        <span className="font-mono font-medium text-foreground">
                          {w.username || formatAddress(w.address)}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-bold">
                        <span className={w.pnl >= 0 ? "text-green-500" : "text-red-500"}>
                          {formatSignedCurrency(w.pnl)}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-muted-fg">
                        {formatPercent(w.win_rate, 0)}
                      </td>
                      <td className="py-3 px-4 text-right font-mono text-muted-fg">
                        {w.balance != null ? formatCurrency(w.balance) : "—"}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <button
                          onClick={() => handleToggleAlert(w.address, w.alerts_enabled)}
                          className={`p-1.5 rounded-lg border transition-colors ${
                            w.alerts_enabled
                              ? "bg-rose-500/10 text-rose-400 border-rose-500/20"
                              : "bg-surface-2 text-muted-fg border-border hover:text-foreground"
                          }`}
                          title={w.alerts_enabled ? "Alerts enabled" : "Enable alerts"}
                        >
                          <Bell size={13} />
                        </button>
                      </td>
                      <td className="py-3 px-4 text-center relative">
                        {groups.length === 0 ? (
                          <span className="text-[11px] text-muted-fg">No groups</span>
                        ) : (
                          <div className="inline-block relative">
                            <button
                              onClick={() => setAddingToGroupWallet(addingToGroupWallet === w.address ? null : w.address)}
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-surface-2 hover:bg-surface-3 border border-border text-foreground"
                            >
                              <Plus size={12} /> Group
                            </button>

                            {addingToGroupWallet === w.address && (
                              <div className="absolute right-0 mt-1 w-44 bg-surface border border-border rounded-lg shadow-lg z-20 p-1 flex flex-col gap-1 text-left">
                                <div className="text-[10px] font-bold text-muted-fg px-2 py-1 uppercase">Select Group</div>
                                {groups.map((g) => (
                                  <button
                                    key={g.id}
                                    onClick={() => handleAddWalletToGroup(g.id, w.address)}
                                    className="px-2 py-1 text-xs text-left hover:bg-primary/10 hover:text-primary rounded truncate transition-colors flex items-center justify-between"
                                  >
                                    <span className="truncate">{g.name}</span>
                                    <Plus size={10} />
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <LikeButton
                          isLiked={true}
                          onToggle={() => handleToggleUnlike(w.address)}
                          size={15}
                          showCount={false}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
