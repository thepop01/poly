"use client";

import { useState } from "react";
import { addCustomWallets } from "@/utils/api";
import { UserPlus, Upload, Trash2, CheckCircle, AlertCircle } from "lucide-react";

export default function CustomWalletsPage() {
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleAddWallets = async () => {
    if (!inputText.trim()) {
      setMessage({ type: "error", text: "Please enter some wallet addresses or CSV format data." });
      return;
    }

    setLoading(true);
    setMessage(null);

    try {
      const lines = inputText.split("\n").map(l => l.trim()).filter(l => l);
      const wallets: { address: string; reason?: string }[] = [];

      for (const line of lines) {
        // Supports plain address OR CSV format: "0x..., Reason here"
        const parts = line.split(",").map(p => p.trim());
        if (parts.length > 0 && parts[0].length === 42 && parts[0].startsWith("0x")) {
          wallets.push({
            address: parts[0],
            reason: parts.length > 1 ? parts.slice(1).join(",").trim() : "Custom User Import",
          });
        }
      }

      if (wallets.length === 0) {
        setMessage({ type: "error", text: "No valid EVM addresses (starting with 0x and 42 chars) found." });
        setLoading(false);
        return;
      }

      const res = await addCustomWallets(wallets);
      if (res.success) {
        setMessage({ type: "success", text: res.message });
        setInputText("");
      } else {
        setMessage({ type: "error", text: res.message || "Failed to add wallets" });
      }
    } catch (e: any) {
      console.error(e);
      setMessage({ type: "error", text: e.message || "An unexpected error occurred." });
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
      setInputText(prev => prev ? prev + "\n" + text : text);
    };
    reader.readAsText(file);
    // Reset input so the same file can be uploaded again if needed
    e.target.value = "";
  };

  return (
    <div className="w-full h-full flex flex-col bg-background max-w-4xl mx-auto p-4 md:p-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
          <UserPlus size={20} className="text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Custom Wallets</h1>
          <p className="text-sm text-muted-fg mt-1">Upload or paste custom wallet addresses to track them.</p>
        </div>
      </div>

      {/* Main Content */}
      <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden flex flex-col">
        <div className="p-4 border-b border-border bg-surface-2/40 flex justify-between items-center">
          <div className="text-sm font-semibold text-foreground">Import Wallets</div>
          <label className="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 bg-surface-2 hover:bg-surface-3 transition-colors border border-border rounded-lg text-xs font-medium text-foreground">
            <Upload size={14} />
            Upload CSV
            <input type="file" accept=".csv,.txt" className="hidden" onChange={handleFileUpload} />
          </label>
        </div>

        <div className="p-4 flex-1 flex flex-col gap-4">
          <div className="bg-surface-2/50 border border-border rounded-lg p-3 text-xs text-muted-fg leading-relaxed">
            <span className="font-semibold text-foreground">Instructions:</span>
            <ul className="list-disc ml-5 mt-1 space-y-1">
              <li>Paste EVM addresses (e.g. <code className="bg-background px-1 rounded">0x...</code>), one per line.</li>
              <li>You can optionally add a reason separated by a comma: <code className="bg-background px-1 rounded">0x..., Alpha Group A</code></li>
              <li>Or upload a `.csv` or `.txt` file containing your list.</li>
            </ul>
          </div>

          <textarea
            className="w-full flex-1 min-h-[250px] bg-background border border-border rounded-lg p-4 text-sm font-mono text-foreground outline-none focus:border-primary resize-y shadow-inner"
            placeholder="0x123..., Twitter Call&#10;0xabc..., Smart Money&#10;..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
          />

          {message && (
            <div className={`flex items-center gap-2 p-3 rounded-lg border text-sm ${
              message.type === "success" 
                ? "bg-green-500/10 text-green-500 border-green-500/20" 
                : "bg-red-500/10 text-red-500 border-red-500/20"
            }`}>
              {message.type === "success" ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
              {message.text}
            </div>
          )}

          <div className="flex justify-end gap-3 mt-2">
            <button
              onClick={() => setInputText("")}
              disabled={loading || !inputText}
              className="px-4 py-2 flex items-center gap-2 rounded-lg text-sm font-semibold border border-border bg-surface-2 text-foreground hover:bg-surface-3 transition-colors disabled:opacity-50"
            >
              <Trash2 size={16} />
              Clear
            </button>
            <button
              onClick={handleAddWallets}
              disabled={loading || !inputText.trim()}
              className="px-6 py-2 flex items-center gap-2 rounded-lg text-sm font-bold bg-primary text-primary-fg hover:bg-primary/90 transition-colors disabled:opacity-50 shadow-sm"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-primary-fg/30 border-t-primary-fg rounded-full animate-spin" />
              ) : (
                <UserPlus size={16} />
              )}
              {loading ? "Adding..." : "Add Wallets"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
