"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Bell, PanelLeft } from "lucide-react";
import { useShell } from "./ShellProvider";
import { useTradeNotifications } from "@/hooks/useTradeNotifications";

const PAGE_TITLES: { prefix: string; title: string; description: string }[] = [
  { prefix: "/dashboard", title: "Dashboard", description: "Your workspace — watchlist, agents, and the live feed" },
  { prefix: "/alpha-calls", title: "Alpha Calls", description: "Live feed of large trades and deposits caught by the scanners" },
  { prefix: "/wallets/curated", title: "Curated Wallets", description: "Curated and global wallets ranked by performance" },
  { prefix: "/wallets/custom", title: "Custom Wallets", description: "Wallets you added by hand" },
  { prefix: "/wallets", title: "Wallets", description: "Every tracked wallet, ranked by performance" },
  { prefix: "/tracker", title: "My Tracker", description: "Your personal wallet lists" },
  { prefix: "/agents", title: "Agents", description: "Conditional rules that monitor the market for you" },
  { prefix: "/wallet/", title: "Wallet", description: "Trader profile and history" },
];

export default function HeaderBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { toggleSidebar } = useShell();
  const { notifications, unreadCount, markRead, clear } = useTradeNotifications();
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const page = PAGE_TITLES.find((p) => pathname.startsWith(p.prefix));

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleDropdown = () => {
    setShowDropdown(!showDropdown);
    if (!showDropdown) markRead();
  };

  const handleNotificationClick = (walletAddress?: string) => {
    setShowDropdown(false);
    if (walletAddress) router.push(`/wallet/${walletAddress}`);
  };

  return (
    <header className="h-16 flex-shrink-0 flex items-center gap-4 px-5 border-b border-border bg-background">
      <button
        onClick={toggleSidebar}
        className="p-2 -ml-2 rounded-lg text-subtle hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
        title="Toggle sidebar"
      >
        <PanelLeft size={18} />
      </button>

      <div className="min-w-0">
        <h1 className="text-base font-bold text-foreground leading-tight truncate">
          {page?.title ?? "PolyTracker"}
        </h1>
        {page?.description && (
          <p className="text-xs text-subtle truncate">{page.description}</p>
        )}
      </div>

      <div className="flex-1" />

      {/* Notifications */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={toggleDropdown}
          className="relative p-2 rounded-lg text-subtle hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
          title="Alerts"
        >
          <Bell size={17} strokeWidth={2} />
          {unreadCount > 0 && (
            <span className="absolute top-1 right-1 min-w-4 h-4 px-1 flex items-center justify-center rounded-full bg-danger text-white text-[9px] font-bold">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>

        {showDropdown && (
          <div className="absolute right-0 top-12 w-80 max-h-96 overflow-y-auto bg-surface border border-border-2 rounded-xl shadow-2xl z-50">
            <div className="p-2.5 border-b border-border flex justify-between items-center bg-surface-2/50 sticky top-0">
              <h3 className="text-xs font-semibold text-foreground">Recent Alerts</h3>
              {notifications.length > 0 && (
                <button
                  onClick={clear}
                  className="text-[10px] text-subtle hover:text-foreground transition-colors cursor-pointer"
                >
                  Clear
                </button>
              )}
            </div>

            <div className="flex flex-col">
              {notifications.length === 0 ? (
                <div className="p-5 text-center text-xs text-subtle">
                  No alerts yet. Whale trades will appear here.
                </div>
              ) : (
                notifications.map((notif, idx) => (
                  <button
                    key={notif.trade_id || idx}
                    onClick={() => handleNotificationClick(notif.wallet_address)}
                    className="p-2.5 text-left border-b border-border hover:bg-surface-2 transition-colors cursor-pointer"
                  >
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[10px] font-mono text-primary truncate max-w-24">
                        {notif.wallet_address?.substring(0, 6)}...{notif.wallet_address?.substring(38)}
                      </span>
                      <span className="text-[9px] text-subtle">
                        {notif.timestamp
                          ? new Date(notif.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                          : ""}
                      </span>
                    </div>
                    <div className="text-xs text-foreground font-medium truncate mb-0.5">
                      {notif.market_title}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`text-[9px] px-1 py-0.5 rounded font-bold ${
                          notif.side === "BUY" ? "text-success bg-success/10" : "text-danger bg-danger/10"
                        }`}
                      >
                        {notif.side}
                      </span>
                      <span className="text-[9px] text-subtle">
                        ${(notif.size || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} at{" "}
                        {notif.price?.toFixed(2)}¢
                      </span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Live status */}
      <div className="live-dot text-xs text-success font-medium whitespace-nowrap">
        Scanners live
      </div>
    </header>
  );
}
