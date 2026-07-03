import React from "react";
import { ArrowRightLeft } from "lucide-react";

export type TradeAlert = {
  id: string;
  market: string;
  side: "Buy" | "Sell";
  outcome: "Yes" | "No";
  amount: string;
  time: string;
};

export default function TradeAlerts({ alerts }: { alerts: TradeAlert[] }) {
  if (!alerts.length) return <div className="text-[#52525B] text-[13px]">No recent alerts.</div>;

  return (
    <div className="space-y-2.5">
      {alerts.map((alert, idx) => (
        <div
          key={alert.id}
          className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-3 flex justify-between items-center relative overflow-hidden group hover:border-[#2a2a2a] transition-all duration-200 animate-slide-in-top"
          style={{ animationDelay: `${idx * 100}ms` }}
        >
          {/* Subtle animated background glow on hover */}
          <div className="absolute inset-0 bg-[#F59E0B]/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          
          <div className="relative z-10 flex gap-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
              alert.side === "Buy" ? "bg-[#22C55E]/10 text-[#22C55E]" : "bg-[#EF4444]/10 text-[#EF4444]"
            }`}>
              <ArrowRightLeft size={14} strokeWidth={2.5} className={alert.side === "Sell" ? "rotate-180" : ""} />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`text-[10px] font-mono font-bold tracking-wider px-1.5 py-0.5 rounded ${
                  alert.side === "Buy" ? "text-[#22C55E] bg-[#22C55E]/10" : "text-[#EF4444] bg-[#EF4444]/10"
                }`}>
                  {alert.side.toUpperCase()}
                </span>
                <span className="text-[#D1D5DB] text-[13px] font-semibold">{alert.market}</span>
              </div>
              <div className="text-[11px] text-[#71717A] flex items-center gap-1.5">
                <span>Outcome: <strong className="text-[#E5E7EB]">{alert.outcome}</strong></span>
              </div>
            </div>
          </div>
          
          <div className="relative z-10 text-right">
            <div className="text-[14px] font-mono font-bold text-[#F8FAFC] mb-0.5">{alert.amount}</div>
            <div className="text-[10px] text-[#52525B] font-mono">{alert.time}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
