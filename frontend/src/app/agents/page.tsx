"use client";

import { useEffect, useState } from "react";
import { listAgents, toggleAgentActive, deleteAgent, listNotifications } from "@/utils/api";
import AgentBuilder from "./AgentBuilder";
import { useAuth } from "@/components/AuthProvider";

export default function AgentsPage() {
  const { token } = useAuth();
  const [agents, setAgents] = useState<any[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    if (!token) return;
    try {
      const [agentsRes, notifsRes] = await Promise.all([
        listAgents(),
        listNotifications()
      ]);
      setAgents(agentsRes.agents || []);
      setNotifications(notifsRes.notifications || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    fetchAll();
    const intv = setInterval(fetchAll, 15000);
    return () => clearInterval(intv);
  }, [token]);

  if (!token) {
    return (
      <div className="p-6 max-w-7xl mx-auto flex flex-col items-center justify-center min-h-[60vh] space-y-4">
        <h1 className="text-3xl font-bold text-white text-center">Agents (Phase 1)</h1>
        <p className="text-gray-400 max-w-md text-center">
          Build conditional rule trees to monitor Polymarket and trigger actions.
          You must be logged in to view and create agents.
        </p>
        <button
          onClick={() => {
            window.location.href = "http://localhost:8000/api/discord/login";
          }}
          className="flex items-center gap-2 px-6 py-3 mt-4 rounded-lg bg-[#5865F2] hover:bg-[#4752C4] text-white font-medium transition-colors"
        >
          Login with Discord
        </button>
      </div>
    );
  }

  const handleToggle = async (id: number, current: boolean) => {
    setAgents(agents.map(a => a.agent_id === id ? { ...a, is_active: !current } : a));
    try {
      await toggleAgentActive(id, !current);
      fetchAll();
    } catch (e) {
      console.error(e);
      fetchAll();
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this agent?")) return;
    try {
      await deleteAgent(id);
      fetchAll();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Agents (Phase 1)</h1>
        <p className="text-gray-400">Build conditional rule trees to monitor Polymarket and trigger actions.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          <AgentBuilder onCreated={fetchAll} />
          
          <div className="bg-[#1E293B] rounded-lg border border-white/10 overflow-hidden">
            <div className="p-4 border-b border-white/10 bg-[#0F172A]/50">
              <h2 className="text-lg font-bold text-white">My Agents</h2>
            </div>
            {loading && agents.length === 0 ? (
              <div className="p-6 text-gray-400 text-center">Loading...</div>
            ) : agents.length === 0 ? (
              <div className="p-6 text-gray-500 text-center">No agents created yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-gray-400 uppercase bg-[#0F172A]/80 border-b border-white/10">
                    <tr>
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Trading</th>
                      <th className="px-4 py-3">Last Fired</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map(a => (
                      <tr key={a.agent_id} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-4 py-3 font-medium text-white">
                          {a.name}
                          {a.description && <div className="text-xs text-gray-500 mt-0.5">{a.description}</div>}
                        </td>
                        <td className="px-4 py-3">
                          <label className="flex items-center cursor-pointer">
                            <div className="relative">
                              <input 
                                type="checkbox" 
                                className="sr-only" 
                                checked={a.is_active}
                                onChange={() => handleToggle(a.agent_id, a.is_active)}
                              />
                              <div className={`block w-10 h-6 rounded-full transition-colors ${a.is_active ? 'bg-blue-500' : 'bg-gray-600'}`}></div>
                              <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${a.is_active ? 'transform translate-x-4' : ''}`}></div>
                            </div>
                          </label>
                        </td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-1 text-xs rounded bg-yellow-500/20 text-yellow-500 font-medium">
                            DRY-RUN
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-400">
                          {a.last_fired_at ? new Date(a.last_fired_at).toLocaleString() : "Never"}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button 
                            onClick={() => handleDelete(a.agent_id)}
                            className="text-red-500 hover:text-red-400 p-1"
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="bg-[#1E293B] rounded-lg border border-white/10 flex flex-col h-[800px]">
            <div className="p-4 border-b border-white/10 bg-[#0F172A]/50 flex justify-between items-center">
              <h2 className="text-lg font-bold text-white">Notifications</h2>
              <span className="text-xs text-gray-400 bg-black/20 px-2 py-1 rounded">
                {notifications.length} Total
              </span>
            </div>
            <div className="p-4 overflow-y-auto flex-1 space-y-3">
              {loading && notifications.length === 0 ? (
                <div className="text-gray-400 text-center mt-10">Loading...</div>
              ) : notifications.length === 0 ? (
                <div className="text-gray-500 text-center mt-10">No notifications yet.</div>
              ) : (
                notifications.map(n => (
                  <div key={n.notification_id} className={`p-3 rounded-lg border ${n.is_read ? 'bg-black/10 border-white/5' : 'bg-blue-900/20 border-blue-500/20'}`}>
                    <div className="flex justify-between items-start mb-1">
                      <h4 className="font-medium text-white text-sm">{n.title}</h4>
                      <span className="text-[10px] text-gray-500">
                        {new Date(n.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 whitespace-pre-wrap">{n.body}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
