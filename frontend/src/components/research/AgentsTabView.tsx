"use client";

import { useEffect, useState } from "react";
import { Bot, Zap, Play, Pause, Trash2, Plus, Shield, Bell, CheckCircle2, Clock, AlertTriangle } from "lucide-react";
import { listAgents, toggleAgentActive, deleteAgent, listNotifications, createAgent } from "@/utils/api";
import { useAuth } from "@/components/AuthProvider";

interface AgentsTabViewProps {
  workspaceId?: string | null;
  onSendPrompt?: (prompt: string) => void;
}

export default function AgentsTabView({ workspaceId, onSendPrompt }: AgentsTabViewProps) {
  const { token } = useAuth();
  const [agents, setAgents] = useState<any[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDesc, setNewAgentDesc] = useState("");
  const [creating, setCreating] = useState(false);

  const fetchAgents = async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const [agentsRes, notifsRes] = await Promise.all([
        listAgents().catch(() => ({ agents: [] })),
        listNotifications().catch(() => ({ notifications: [] })),
      ]);
      setAgents(agentsRes?.agents || []);
      setNotifications(notifsRes?.notifications || []);
    } catch (err) {
      console.error("Failed to load agents in workspace:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgents();
    const interval = setInterval(fetchAgents, 15000);
    return () => clearInterval(interval);
  }, [token]);

  const handleToggle = async (agentId: number, currentActive: boolean) => {
    setAgents((prev) =>
      prev.map((a) => (a.agent_id === agentId ? { ...a, is_active: !currentActive } : a))
    );
    try {
      await toggleAgentActive(agentId, !currentActive);
      fetchAgents();
    } catch (err) {
      console.error("Failed to toggle agent active state:", err);
      fetchAgents();
    }
  };

  const handleDelete = async (agentId: number, name: string) => {
    if (!confirm(`Delete agent "${name}"?`)) return;
    try {
      await deleteAgent(agentId);
      setAgents((prev) => prev.filter((a) => a.agent_id !== agentId));
    } catch (err) {
      console.error("Failed to delete agent:", err);
    }
  };

  const handleQuickCreate = async (templateName: string, description: string, rule: any) => {
    setCreating(true);
    try {
      await createAgent({
        name: templateName,
        description,
        rule_tree: rule,
        actions: [{ action_type: "notify", params: { channel: "in_app" } }],
        cooldown_seconds: 3600,
      });
      setShowCreateModal(false);
      await fetchAgents();
    } catch (err) {
      console.error("Failed to create agent:", err);
    } finally {
      setCreating(false);
    }
  };

  if (loading && agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-center p-8">
        <Bot size={24} className="text-primary animate-pulse" />
        <span className="text-xs font-bold text-subtle">Loading workspace agents…</span>
      </div>
    );
  }

  return (
    <div className="research-canvas-body p-6 w-full space-y-6 max-w-5xl" data-testid="agents-tab-view">
      {/* Header bar */}
      <div className="flex items-center justify-between gap-4 pb-4 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold text-foreground">Workspace Automation Agents</h2>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-primary/10 text-primary border border-primary/20">
              {agents.filter((a) => a.is_active).length} Active · {agents.length} Total
            </span>
          </div>
          <p className="text-xs font-medium text-subtle mt-0.5">
            Monitor Polymarket conditions and trigger automated notifications or orders.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-white text-xs font-bold transition-all shadow-xs cursor-pointer"
        >
          <Plus size={13} className="stroke-[2.5]" />
          <span>New Agent</span>
        </button>
      </div>

      {/* Agents grid or empty state */}
      {agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed border-border rounded-xl bg-surface/40 space-y-4">
          <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            <Bot size={24} />
          </div>
          <div className="max-w-md">
            <h3 className="text-sm font-bold text-foreground">No Automation Agents in this Workspace</h3>
            <p className="text-xs text-subtle font-medium mt-1 leading-normal">
              Agents monitor live markets and wallets 24/7. Choose a template below or ask the Research Terminal to craft a rule tree.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full max-w-2xl pt-2">
            <button
              type="button"
              onClick={() =>
                handleQuickCreate(
                  "Whale Accumulation Alert",
                  "Alert when any tracked wallet buys YES > $5,000",
                  { condition: "whale_trade", min_amount: 5000, outcome: "YES" }
                )
              }
              className="p-3.5 rounded-lg border border-border bg-surface hover:bg-surface-2 text-left transition-all group cursor-pointer"
            >
              <div className="flex items-center gap-2 text-xs font-bold text-foreground group-hover:text-primary">
                <Zap size={13} className="text-primary" />
                <span>Whale Accumulation</span>
              </div>
              <p className="text-[11px] text-subtle font-medium mt-1">
                Alerts when large wallet buys YES &gt; $5,000 in tracked markets.
              </p>
            </button>

            <button
              type="button"
              onClick={() =>
                handleQuickCreate(
                  "Cricket Sharp Consensus",
                  "Notify when &gt;3 cricket wallets agree on YES outcome",
                  { condition: "consensus", category: "Cricket", min_wallets: 3, outcome: "YES" }
                )
              }
              className="p-3.5 rounded-lg border border-border bg-surface hover:bg-surface-2 text-left transition-all group cursor-pointer"
            >
              <div className="flex items-center gap-2 text-xs font-bold text-foreground group-hover:text-primary">
                <Shield size={13} className="text-primary" />
                <span>Sharp Consensus</span>
              </div>
              <p className="text-[11px] text-subtle font-medium mt-1">
                Triggers when &ge;3 top wallets take the same side.
              </p>
            </button>

            <button
              type="button"
              onClick={() =>
                handleQuickCreate(
                  "High PnL Wallet Mirror",
                  "Monitor top 10 PnL wallets for new entries",
                  { condition: "top_pnl_entry", rank_limit: 10 }
                )
              }
              className="p-3.5 rounded-lg border border-border bg-surface hover:bg-surface-2 text-left transition-all group cursor-pointer"
            >
              <div className="flex items-center gap-2 text-xs font-bold text-foreground group-hover:text-primary">
                <Bell size={13} className="text-primary" />
                <span>Top Wallet Monitor</span>
              </div>
              <p className="text-[11px] text-subtle font-medium mt-1">
                Tracks when top ranked wallets open fresh positions.
              </p>
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {agents.map((agent) => {
            const isActive = agent.is_active;
            const isArmed = agent.trading_armed;
            return (
              <div
                key={agent.agent_id}
                className={`p-4 rounded-xl border bg-surface transition-all ${
                  isActive ? "border-primary/40 shadow-xs" : "border-border opacity-75"
                }`}
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={`p-1.5 rounded-lg ${isActive ? "bg-primary/10 text-primary" : "bg-surface-2 text-subtle"}`}>
                      <Bot size={16} />
                    </div>
                    <div className="min-w-0">
                      <h4 className="text-sm font-bold text-foreground truncate">{agent.name}</h4>
                      <p className="text-[11px] text-subtle font-medium truncate">
                        {agent.description || "Custom trigger rule tree"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => handleToggle(agent.agent_id, isActive)}
                      title={isActive ? "Pause agent" : "Activate agent"}
                      className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold transition-all cursor-pointer ${
                        isActive
                          ? "bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20"
                          : "bg-surface-2 text-subtle border border-border hover:text-foreground"
                      }`}
                    >
                      {isActive ? <Play size={10} className="fill-current" /> : <Pause size={10} />}
                      <span>{isActive ? "Active" : "Paused"}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleDelete(agent.agent_id, agent.name)}
                      title="Delete agent"
                      className="p-1 rounded-md text-subtle hover:text-danger hover:bg-surface-2 transition-colors cursor-pointer"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* Rule & actions summary */}
                <div className="mt-3 p-2.5 rounded-lg bg-surface-2/60 border border-border/80 text-xs space-y-1.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-subtle font-semibold">Trading Gate:</span>
                    <span className={`font-bold ${isArmed ? "text-warning" : "text-subtle"}`}>
                      {isArmed ? "ARMED (Mock/Test)" : "Disarmed (Alerts only)"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-subtle font-semibold">Cooldown:</span>
                    <span className="font-mono font-bold text-foreground">
                      {agent.cooldown_seconds ? `${Math.round(agent.cooldown_seconds / 60)}m` : "None"}
                    </span>
                  </div>

                  {agent.last_fired_at && (
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-subtle font-semibold">Last Fired:</span>
                      <span className="font-medium text-foreground">
                        {new Date(agent.last_fired_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal for manual agent creation */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-border">
              <h3 className="text-sm font-bold text-foreground">Create Automation Agent</h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-subtle hover:text-foreground text-sm font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Agent Name</label>
                <input
                  type="text"
                  value={newAgentName}
                  placeholder="e.g. Cricket Whale Tracker"
                  onChange={(e) => setNewAgentName(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-border bg-surface text-xs font-semibold text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground mb-1">Description</label>
                <input
                  type="text"
                  value={newAgentDesc}
                  placeholder="e.g. Alert when smart money accumulates YES"
                  onChange={(e) => setNewAgentDesc(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-border bg-surface text-xs font-semibold text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  disabled={!newAgentName.trim() || creating}
                  onClick={() =>
                    handleQuickCreate(
                      newAgentName.trim(),
                      newAgentDesc.trim(),
                      { condition: "active_monitor", target: newAgentName }
                    )
                  }
                  className="w-full py-2 rounded-lg bg-primary hover:bg-primary/90 disabled:opacity-50 text-white text-xs font-bold transition-all cursor-pointer shadow-xs"
                >
                  {creating ? "Creating…" : "Create Agent"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
