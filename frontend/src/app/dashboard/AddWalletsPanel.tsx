"use client";

import React, { useState } from "react";
import { UserPlus, Upload, Trash2, CheckCircle, AlertCircle, Sparkles } from "lucide-react";
import { addCustomWallets, toggleWatchlist } from "@/utils/api";

export function AddWalletsPanel({ onWalletsAdded }: { onWalletsAdded?: () => void }) {
  const [mode, setMode] = useState<"single" | "bulk">("single");
  const [singleAddress, setSingleAddress] = useState("");
  const [singleLabel, setSingleLabel] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleSingleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const addr = singleAddress.trim();
    if (!addr || addr.length !== 42 || !addr.startsWith("0x")) {
      setMessage({ type: "error", text: "Invalid EVM address (must start with 0x and be 42 chars)." });
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const res = await addCustomWallets([{ address: addr, reason: singleLabel.trim() || "Single Import" }]);
      if (res.success) {
        await toggleWatchlist(addr).catch(() => {});
        setMessage({ type: "success", text: "Wallet added to tracked wallets!" });
        setSingleAddress("");
        setSingleLabel("");
        if (onWalletsAdded) onWalletsAdded();
      } else {
        setMessage({ type: "error", text: res.message || "Failed to add wallet." });
      }
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "An error occurred." });
    } finally {
      setLoading(false);
    }
  };

  const handleBulkAdd = async () => {
    if (!bulkText.trim()) {
      setMessage({ type: "error", text: "Please enter address list or upload a CSV." });
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const lines = bulkText.split("\n").map((l) => l.trim()).filter(Boolean);
      const wallets: { address: string; reason?: string }[] = [];

      for (const line of lines) {
        const parts = line.split(",").map((p) => p.trim());
        if (parts[0] && parts[0].length === 42 && parts[0].startsWith("0x")) {
          wallets.push({
            address: parts[0],
            reason: parts.length > 1 ? parts.slice(1).join(",").trim() : "Bulk Import",
          });
        }
      }

      if (wallets.length === 0) {
        setMessage({ type: "error", text: "No valid 0x EVM addresses found." });
        setLoading(false);
        return;
      }

      const res = await addCustomWallets(wallets);
      if (res.success) {
        for (const w of wallets) {
          await toggleWatchlist(w.address).catch(() => {});
        }
        setMessage({ type: "success", text: res.message || `Added ${wallets.length} wallets to tracked!` });
        setBulkText("");
        if (onWalletsAdded) onWalletsAdded();
      } else {
        setMessage({ type: "error", text: res.message || "Failed to add wallets." });
      }
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "An error occurred." });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setBulkText((prev) => (prev ? prev + "\n" + text : text));
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  return (
    <div className="card p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <UserPlus size={16} className="text-primary" />
          <h2 className="text-sm font-bold text-foreground">Add Wallets</h2>
        </div>
        {/* Toggle Mode */}
        <div className="flex items-center p-0.5 bg-surface-2 rounded-lg border border-border">
          <button
            onClick={() => { setMode("single"); setMessage(null); }}
            className={`px-2 py-0.5 text-[11px] font-medium rounded-md transition-colors ${
              mode === "single"
                ? "bg-surface text-foreground font-semibold shadow-xs"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            Single
          </button>
          <button
            onClick={() => { setMode("bulk"); setMessage(null); }}
            className={`px-2 py-0.5 text-[11px] font-medium rounded-md transition-colors ${
              mode === "bulk"
                ? "bg-surface text-foreground font-semibold shadow-xs"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            Bulk
          </button>
        </div>
      </div>

      {/* Forms */}
      {mode === "single" ? (
        <form onSubmit={handleSingleAdd} className="flex flex-col gap-2.5">
          <div>
            <label className="text-[11px] font-medium text-muted-fg mb-1 block">Wallet Address *</label>
            <input
              type="text"
              placeholder="0x..."
              value={singleAddress}
              onChange={(e) => setSingleAddress(e.target.value)}
              className="w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-xs font-mono outline-none focus:border-primary text-foreground placeholder:text-muted-fg/60"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-fg mb-1 block">Label / Reason (Optional)</label>
            <input
              type="text"
              placeholder="e.g. Smart Trader A"
              value={singleLabel}
              onChange={(e) => setSingleLabel(e.target.value)}
              className="w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder:text-muted-fg/60"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !singleAddress.trim()}
            className="mt-1 w-full py-1.5 rounded-lg bg-primary text-primary-fg hover:bg-primary/90 text-xs font-bold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5 shadow-xs"
          >
            {loading ? (
              <div className="w-3.5 h-3.5 border-2 border-primary-fg/30 border-t-primary-fg rounded-full animate-spin" />
            ) : (
              <UserPlus size={14} />
            )}
            {loading ? "Adding..." : "Track Wallet"}
          </button>
        </form>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-medium text-muted-fg">Paste Addresses or CSV</label>
            <label className="cursor-pointer inline-flex items-center gap-1 text-[10px] font-medium text-primary hover:underline">
              <Upload size={12} />
              CSV File
              <input type="file" accept=".csv,.txt" className="hidden" onChange={handleFileUpload} />
            </label>
          </div>
          <textarea
            rows={4}
            placeholder="0x123..., Smart Money&#10;0x456..., Whale Call"
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            className="w-full bg-background border border-border rounded-lg p-2 text-xs font-mono outline-none focus:border-primary text-foreground placeholder:text-muted-fg/60 resize-none"
          />
          <div className="flex items-center justify-end gap-2 mt-1">
            {bulkText && (
              <button
                type="button"
                onClick={() => setBulkText("")}
                className="px-2 py-1 text-[11px] font-medium text-muted-fg hover:text-foreground border border-border rounded-md bg-surface-2"
              >
                Clear
              </button>
            )}
            <button
              type="button"
              onClick={handleBulkAdd}
              disabled={loading || !bulkText.trim()}
              className="flex-1 py-1.5 rounded-lg bg-primary text-primary-fg hover:bg-primary/90 text-xs font-bold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5 shadow-xs"
            >
              {loading ? (
                <div className="w-3.5 h-3.5 border-2 border-primary-fg/30 border-t-primary-fg rounded-full animate-spin" />
              ) : (
                <Upload size={14} />
              )}
              {loading ? "Importing..." : "Import List"}
            </button>
          </div>
        </div>
      )}

      {/* Message Feedback */}
      {message && (
        <div
          className={`flex items-center gap-1.5 p-2 rounded-lg border text-[11px] ${
            message.type === "success"
              ? "bg-green-500/10 text-green-500 border-green-500/20"
              : "bg-red-500/10 text-red-500 border-red-500/20"
          }`}
        >
          {message.type === "success" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          <span className="flex-1">{message.text}</span>
        </div>
      )}
    </div>
  );
}
