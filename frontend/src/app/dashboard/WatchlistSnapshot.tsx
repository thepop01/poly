"use client";

import Link from "next/link";
import { formatCurrency, formatSignedCurrency, formatAddress, toNum } from "@/utils/format";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";
import { Wallet } from "lucide-react";

export interface WatchlistEntry {
  address: string;
  username?: string | null;
  pnl?: number | string | null;
  balance?: number | string | null;
}

export function WatchlistSnapshot({ wallets }: { wallets: WatchlistEntry[] }) {
  return (
    <div className="card p-5">
      <div className="mb-4">
        <h2 className="text-base font-bold text-foreground">Watchlist snapshot</h2>
        <p className="text-xs text-subtle">The wallets you follow, ranked by realized PnL.</p>
      </div>

      {wallets.length === 0 ? (
        <EmptyState
          icon={<Wallet size={22} />}
          title="No wallets on your watchlist yet"
          hint="Add wallets from the Wallets page to see them here."
        />
      ) : (
        <div className="divide-y divide-border">
          {wallets.map((w) => {
            const pnl = toNum(w.pnl);
            return (
              <Link
                key={w.address}
                href={`/wallet/${w.address}`}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0 group"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Avatar name={w.username} address={w.address} size={28} />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                      {w.username || formatAddress(w.address)}
                    </div>
                    <div className="text-[11px] font-mono text-subtle">{formatAddress(w.address)}</div>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div
                    className={`text-sm font-mono font-bold ${
                      pnl != null && pnl < 0 ? "text-danger" : "text-primary"
                    }`}
                  >
                    {formatSignedCurrency(w.pnl)}
                  </div>
                  <div className="text-[11px] font-mono text-subtle">
                    {formatCurrency(toNum(w.balance) ?? 0)} balance
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
