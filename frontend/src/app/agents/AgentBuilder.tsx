"use client";

import { useState } from "react";
import { createAgent } from "@/utils/api";

const ALLOWED_FIELDS = [
  "current_price",
  "total_volume",
  "liquidity",
  "price_change_1h_pct",
  "price_change_24h_pct",
  "hours_to_resolution",
];

const CMP_OPS = [
  { value: "lt", label: "<" },
  { value: "lte", label: "<=" },
  { value: "gt", label: ">" },
  { value: "gte", label: ">=" },
  { value: "eq", label: "==" },
  { value: "ne", label: "!=" },
];

export default function AgentBuilder({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [op, setOp] = useState("and");
  const [conditions, setConditions] = useState([{ field: "current_price", cmp: "lt", value: 0.15 }]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addCondition = () => {
    setConditions([...conditions, { field: "current_price", cmp: "lt", value: 0.15 }]);
  };

  const updateCondition = (index: number, key: string, val: string | number) => {
    const newConds = [...conditions];
    newConds[index] = { ...newConds[index], [key]: val };
    setConditions(newConds);
  };

  const removeCondition = (index: number) => {
    if (conditions.length === 1) return;
    const newConds = [...conditions];
    newConds.splice(index, 1);
    setConditions(newConds);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;
    setLoading(true);
    setError(null);
    try {
      const rule_tree = conditions.length === 1
        ? conditions[0]
        : { op, children: conditions };
      
      const actions = [
        { action_type: "notify", params: { message } }
      ];

      await createAgent({ name, description, rule_tree, actions });
      setName("");
      setDescription("");
      setConditions([{ field: "current_price", cmp: "lt", value: 0.15 }]);
      setMessage("");
      onCreated();
    } catch (err: any) {
      setError(err.message || "Failed to create agent");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-[#1E293B] p-6 rounded-lg mb-8 border border-white/10">
      <h2 className="text-xl font-bold mb-4 text-white">Create New Agent</h2>
      {error && <div className="text-red-500 mb-4">{error}</div>}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Name</label>
            <input 
              required
              value={name} 
              onChange={e => setName(e.target.value)} 
              className="w-full bg-[#0F172A] border border-white/10 rounded-lg px-3 py-2 text-white" 
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Description</label>
            <input 
              value={description} 
              onChange={e => setDescription(e.target.value)} 
              className="w-full bg-[#0F172A] border border-white/10 rounded-lg px-3 py-2 text-white" 
            />
          </div>
        </div>

        <div>
          <div className="flex items-center gap-4 mb-2">
            <h3 className="text-md font-semibold text-white">Conditions</h3>
            {conditions.length > 1 && (
              <select 
                value={op} 
                onChange={e => setOp(e.target.value)}
                className="bg-[#0F172A] border border-white/10 rounded-lg px-2 py-1 text-white text-sm"
              >
                <option value="and">ALL (AND)</option>
                <option value="or">ANY (OR)</option>
              </select>
            )}
          </div>
          <div className="space-y-3">
            {conditions.map((cond, i) => (
              <div key={i} className="flex gap-3 items-center">
                <select 
                  value={cond.field} 
                  onChange={e => updateCondition(i, "field", e.target.value)}
                  className="bg-[#0F172A] border border-white/10 rounded-lg px-3 py-2 text-white flex-1"
                >
                  {ALLOWED_FIELDS.map(f => <option key={f} value={f}>{f}</option>)}
                </select>
                <select 
                  value={cond.cmp} 
                  onChange={e => updateCondition(i, "cmp", e.target.value)}
                  className="bg-[#0F172A] border border-white/10 rounded-lg px-3 py-2 text-white w-24"
                >
                  {CMP_OPS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
                <input 
                  type="number" 
                  step="any"
                  required
                  value={cond.value} 
                  onChange={e => updateCondition(i, "value", parseFloat(e.target.value))} 
                  className="bg-[#0F172A] border border-white/10 rounded-lg px-3 py-2 text-white w-32" 
                />
                {conditions.length > 1 && (
                  <button type="button" onClick={() => removeCondition(i)} className="text-red-500 hover:text-red-400 p-2">✕</button>
                )}
              </div>
            ))}
          </div>
          <button type="button" onClick={addCondition} className="text-sm text-blue-400 mt-3 hover:text-blue-300">
            + Add Condition
          </button>
        </div>

        <div>
          <h3 className="text-md font-semibold text-white mb-2">Actions</h3>
          <div className="space-y-4">
            <div className="bg-[#0F172A] p-4 rounded-lg border border-white/10">
              <label className="flex items-center gap-2 text-white font-medium mb-3">
                <input type="checkbox" checked disabled className="rounded border-white/10 bg-black/20" />
                Notify
              </label>
              <div className="ml-6">
                <label className="block text-sm text-gray-400 mb-1">Custom Message</label>
                <input 
                  value={message} 
                  onChange={e => setMessage(e.target.value)} 
                  className="w-full bg-black/20 border border-white/10 rounded-lg px-3 py-2 text-white" 
                  placeholder="Optional alert message..."
                />
              </div>
            </div>
            
            <div className="bg-[#0F172A]/50 p-4 rounded-lg border border-white/10 opacity-60">
              <label className="flex items-center gap-2 text-white font-medium mb-1">
                <input type="checkbox" disabled className="rounded border-white/10" />
                Trade (Coming Soon)
              </label>
              <p className="ml-6 text-sm text-gray-400">Arm trading to automatically place orders (Phase 1 brokers dry-run only).</p>
            </div>
          </div>
        </div>

        <button 
          type="submit" 
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-6 rounded-lg transition-colors"
        >
          {loading ? "Creating..." : "Create Agent"}
        </button>
      </form>
    </div>
  );
}
