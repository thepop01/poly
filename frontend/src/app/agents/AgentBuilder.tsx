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
    <div className="card p-6 mb-8">
      <h2 className="text-xl font-bold mb-4 text-foreground">Create New Agent</h2>
      {error && <div className="text-danger mb-4 text-sm font-medium">{error}</div>}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-subtle mb-1.5">Name</label>
            <input 
              required
              value={name} 
              onChange={e => setName(e.target.value)} 
              className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-primary outline-none transition-colors" 
              placeholder="e.g. Whale Tracker Alpha"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-subtle mb-1.5">Description</label>
            <input 
              value={description} 
              onChange={e => setDescription(e.target.value)} 
              className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-foreground text-sm focus:border-primary outline-none transition-colors" 
              placeholder="Brief description of this agent"
            />
          </div>
        </div>

        <div>
          <div className="flex items-center gap-4 mb-2">
            <h3 className="text-sm font-bold uppercase tracking-wider text-foreground">Conditions</h3>
            {conditions.length > 1 && (
              <select 
                value={op} 
                onChange={e => setOp(e.target.value)}
                className="bg-surface-2 border border-border rounded-lg px-2 py-1 text-foreground text-xs font-medium focus:border-primary outline-none"
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
                  className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-foreground text-xs font-medium flex-1 focus:border-primary outline-none"
                >
                  {ALLOWED_FIELDS.map(f => <option key={f} value={f}>{f}</option>)}
                </select>
                <select 
                  value={cond.cmp} 
                  onChange={e => updateCondition(i, "cmp", e.target.value)}
                  className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-foreground text-xs font-medium w-24 focus:border-primary outline-none"
                >
                  {CMP_OPS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
                <input 
                  type="number" 
                  step="any"
                  required
                  value={cond.value} 
                  onChange={e => updateCondition(i, "value", parseFloat(e.target.value))} 
                  className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-foreground text-xs font-mono w-32 focus:border-primary outline-none" 
                />
                {conditions.length > 1 && (
                  <button type="button" onClick={() => removeCondition(i)} className="text-danger hover:opacity-80 p-2 cursor-pointer">✕</button>
                )}
              </div>
            ))}
          </div>
          <button type="button" onClick={addCondition} className="text-xs font-semibold text-primary mt-3 hover:underline cursor-pointer">
            + Add Condition
          </button>
        </div>

        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-foreground mb-2">Actions</h3>
          <div className="space-y-4">
            <div className="bg-surface-2/60 p-4 rounded-xl border border-border">
              <label className="flex items-center gap-2 text-foreground font-semibold text-xs mb-3">
                <input type="checkbox" checked disabled className="rounded border-border" />
                Notify
              </label>
              <div className="ml-6">
                <label className="block text-xs text-subtle mb-1 font-medium">Custom Message</label>
                <input 
                  value={message} 
                  onChange={e => setMessage(e.target.value)} 
                  className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-foreground text-xs focus:border-primary outline-none" 
                  placeholder="Optional alert message..."
                />
              </div>
            </div>
            
            <div className="bg-surface-2/30 p-4 rounded-xl border border-border opacity-70">
              <label className="flex items-center gap-2 text-foreground font-semibold text-xs mb-1">
                <input type="checkbox" disabled className="rounded border-border" />
                Trade (Coming Soon)
              </label>
              <p className="ml-6 text-xs text-subtle">Arm trading to automatically place orders (Phase 1 brokers dry-run only).</p>
            </div>
          </div>
        </div>

        <button 
          type="submit" 
          disabled={loading}
          className="bg-primary hover:bg-primary/90 text-white font-semibold py-2 px-6 rounded-lg transition-colors cursor-pointer text-xs shadow-sm disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create Agent"}
        </button>
      </form>
    </div>
  );
}
