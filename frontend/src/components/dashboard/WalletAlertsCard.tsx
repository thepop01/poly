"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Bell, Zap, ArrowUpRight } from "lucide-react";
import { getTrackedWalletAlerts } from "@/utils/api";
import { formatCurrency, timeAgo } from "@/utils/format";
import { TypeBadge } from "@/components/ui/TypeBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { useAuth } from "@/components/AuthProvider";

export interface TrackedAlertItem {
  id: number;
  address: string;
  alert_type: "LARGE_TRADE" | "LARGE_DEPOSIT";
  market_title?: string | null;
  amount_usdc: number;
  created_at: string;
  wallet_name?: string | null;
}

export function WalletAlertsCard() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<TrackedAlertItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    getTrackedWalletAlerts(6)
      .then((res) => {
        if (!cancelled && res?.alerts) {
          setAlerts(res.alerts);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="card p-5 flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bell size={18} className="text-rose-400" />
          <div>
            <h2 className="text-base font-bold text-foreground">Tracked Wallet Alerts</h2>
            <p className="text-xs text-subtle">Activity from your favorited wallets.</p>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center py-8">
          <div className="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : alerts.length === 0 ? (
        <EmptyState
          icon={<Zap size={22} />}
          title="No activity from tracked wallets yet"
          hint="Like or track wallets to get live activity alerts here."
        />
      ) : (
        <div className="divide-y divide-border flex-1">
          {alerts.map((item, index) => {
            const t = timeAgo(item.created_at);
            const isDeposit = item.alert_type === "LARGE_DEPOSIT";

            return (
              <div key={`${item.id}-${index}`} className="flex items-center justify-between gap-3 py-3 first:pt-0">
                <div className="flex items-center gap-2.5 min-w-0">
                  <TypeBadge kind={isDeposit ? "deposit" : "trade"} />
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-foreground truncate block">
                      {item.wallet_name || item.address.slice(0, 6) + "..." + item.address.slice(-4)}
                    </span>
                    <div className="text-[11px] text-subtle truncate">
                      {item.market_title || (isDeposit ? "USDC deposit" : "—")}
                    </div>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-sm font-mono font-bold text-foreground">
                    {formatCurrency(item.amount_usdc)}
                  </div>
                  <div className="text-[11px] text-subtle">{t?.relative ?? ""}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
