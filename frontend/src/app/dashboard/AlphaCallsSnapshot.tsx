"use client";

import Link from "next/link";
import { formatCurrency, timeAgo } from "@/utils/format";
import { TypeBadge } from "@/components/ui/TypeBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Zap, ArrowUpRight } from "lucide-react";

export interface AlphaSnapshotItem {
  id: string;
  type: "trade" | "deposit";
  address?: string;
  username?: string | null;
  market_title?: string | null;
  amount?: number | null;
  timestamp?: string | null;
}

export function AlphaCallsSnapshot({ items }: { items: AlphaSnapshotItem[] }) {
  return (
    <div className="card p-5 flex flex-col">
      <div className="mb-4">
        <h2 className="text-base font-bold text-foreground">Latest feed activity</h2>
        <p className="text-xs text-subtle">Fresh signals from the trade and deposit scanners.</p>
      </div>

      {items.length === 0 ? (
        <EmptyState icon={<Zap size={22} />} title="No signals in the current window" />
      ) : (
        <div className="divide-y divide-border flex-1">
          {items.map((item, index) => {
            const t = timeAgo(item.timestamp);
            return (
              <div key={`${item.id}-${index}`} className="flex items-center justify-between gap-3 py-3 first:pt-0">
                <div className="flex items-center gap-2.5 min-w-0">
                  <TypeBadge kind={item.type} />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {item.username || "Wallet"}
                    </div>
                    <div className="text-[11px] text-subtle truncate">
                      {item.market_title || (item.type === "deposit" ? "USDC deposit" : "—")}
                    </div>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-sm font-mono font-bold text-foreground">
                    {formatCurrency(item.amount ?? 0)}
                  </div>
                  <div className="text-[11px] text-subtle">{t?.relative ?? ""}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Link
        href="/feed"
        className="mt-4 inline-flex items-center gap-1.5 self-start px-3 py-1.5 rounded-lg bg-surface-2 border border-border text-xs font-medium text-foreground hover:bg-surface-3 transition-colors"
      >
        Open full feed <ArrowUpRight size={13} />
      </Link>
    </div>
  );
}
